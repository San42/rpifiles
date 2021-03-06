#!/usr/bin/python3
#fix for the imports
import os
import pymodbus
import serial
import struct
import numpy as np
from pymodbus.client.sync import ModbusSerialClient as MC
import time
import getopt
import datetime
from AWSclient import AWSclient
from localdb import localdb
import threading
#class containing the methods for iterative reading of data and publishing to mqtt
class modbus_rtu():

#Initilizing the parameters for the class instance
  serial_no="" #usb cable
  sensor_id=[] 
  stop_bits=[]
  byte_size=[]
  par="" #parity
  baud_rate=[]
  addrs=[] #modbus address
  count=[] #count for each register
  ut=0 #unit id of the modbus
  cov=[] #change of value fraction/percentage
  u=[] #unit of the data
  type=[] #what the data represents : eg. temperature, resistance etc
  scale=1
  signed=1
  dtype=1
  name=""
  aws=AWSclient()
  myAWSIoTMQTTClient=aws.myAWSIoTMQTTClient
  conn=aws.conn
  dead=False

  def __init__(self,serial_no,sensor_id,stop_bits,byte_size,par,baud_rate,addrs,count,ut,cov,u,type,scale,signed,name):
    self.serial_no=serial_no
    self.sensor_id=sensor_id
    self.stop_bits=stop_bits
    self.byte_size=byte_size
    self.par=par
    self.baud_rate=baud_rate
    self.addrs=addrs
    self.count=count
    self.ut=ut
    self.cov=cov
    self.u=u
    self.type=type
    self.scale=scale.astype(float)
    self.signed=signed
    self.name=name
    self.publish_to_mqtt()

#Function to convert the raw values to float
  def to_float(self,og_type,data):
    if og_type==1:
      s= data
    elif og_type==2: #Checking the type of raw vaue . Here 2 ='floating-point'
      ms=hex(data[0]) #most significant in hexa-decimal
      ls=hex(data[1]) # least significant in hexa-decimal
      val_hex=ms[2:]+ls[2:] # combining
      val_f=0
      try:
        val_f=struct.unpack('f',struct.pack('i',int(val_hex,16))) # converting from floating point hex to decimal
      except:
        pass

# getting rid of the 'brackets' in the string containing the final decimal value after conversion
      s=str(val_f)
      chars='(,)'
      for ch in chars:
         s=s.replace(ch,"")
    return s

# Publishing  to mqtt
  def pub(self,timestamp,sensor_id,s,units,type):
    aws=AWSclient()
    myAWSIoTMQTTClient=aws.myAWSIoTMQTTClient
    conn=aws.conn
    topic = "NE/RPi"
    msg = '"Time": "{}", "Device":"{}", "Value": "{}","Units":"{}","Type":"{}"'.format(timestamp,sensor_id,s,units,type)
    msg = '{'+msg+'}'
    self.myAWSIoTMQTTClient.publish(topic, msg, 1)

  def publish_to_mqtt(self):
#Publish to the topic in a loop
    loopCount = 0
    delay_read = 5 # delay in seconds for reading the sensor
    u1=self.u
  #Configuring the port address
  #p='/dev/serial/by-id/usb-ATC_USB_High_Speed_RS-485_Converter_'+serial_no+'-if00-port0'
  #getting the device-id's of the USBs in the directory
    dir=os.listdir('/dev/serial/by-id')
  #Taking the device path id which contains the serial number given
    for dv in dir:
        if self.serial_no in dv:
          p = '/dev/serial/by-id/'+dv
        else:
          raise Exception('{} USB device not found'.format(serial_no))
    p='/dev/ttyUSB0'
#Passing the arguments for establishing connection with modbus rtu device: MC-> ModbusSerialClient
#    print(p,self.stop_bits,self.byte_size,self.par,self.baud_rate)
    c = MC(method='rtu',port=p,stopbits=self.stop_bits,
         bytesize=self.byte_size,parity=self.par,baudrate=self.baud_rate)
    con = c.connect()
#    print(con)
#getting the dimensions of the sensor_id 2d array
    dim_rgstrs=np.shape(self.sensor_id)
#    print(dim_rgstrs)
    try:
          while (not self.dead):
                  loopCount += 1
                  timestamp = datetime.datetime.now()
#Initializing variables for the values in last read and current read for checking the CoV condition
                  if loopCount==1:
                     last_val=(np.zeros((dim_rgstrs[0],dim_rgstrs[1]))).astype(str)
                  new_val=(np.zeros((dim_rgstrs[0],dim_rgstrs[1]))).astype(str)
#Loop for reading the registers: Outer loop(j=rows) for transversing each device (boilers), inner loop(i=columns) for each register
                  for j in range(dim_rgstrs[0]):
                    for i in range(dim_rgstrs[1]):
 #                     print(self.addrs[j,i])
                      if (self.addrs[j,i])!='':
#Reading the values after checking the regitser addresses(input or holding)
                        if int(self.addrs[j,i])>=30000 and int(self.addrs[j,i])<40000:
                          r = c.read_input_registers(int(self.addrs[j,i])-30001,int(self.count[j,i]),unit=int(self.ut[j]))
                        else:
                          r = c.read_holding_registers(int(self.addrs[j,i])-40001,int(self.count[j,i]),unit=int(self.ut[j]))
                        data=r.registers
                       # print(data)
                       # print('dev no: {}'.format(self.ut[j]))

# Conversion to decimal from the raw data type
                        s=(self.to_float(self.dtype,data[0]))
#Checking if data is signed and ten converting accordingly
                        if self.signed[j,i]!=1:
                           if s>32767:
                             s=s-65535
                        s=s*(self.scale[j,i])
#Converting to Farhenheit
#                        if self.u[j,i]=="C":
#                          print("INSIDE")
#                           s=(s*9/5)+32
#                           u1[j,i]="F"
# storing the previous values and checking for CoV
                        if loopCount==1:
                          last_val[j,i]=s

                          new_val[j,i]=s
                        else:
                          new_val[j,i]=s
                       # print(' last: "{}", current:"{}"'.format(last_val,new_val))

# Checking the CoV condition and publishing if satifies
                          try:
                             if (abs(float(new_val[j,i])-float(last_val[j,i]))>float(self.cov[j,i])):
                                print("Value greater than CoV")
                                self.pub(timestamp,self.sensor_id[j,i],s,u1[j,i],self.name[j,i])
                          except ZeroDivisionError:
                             print(float('inf'))
                        print(' Loop {:d}'.format(loopCount))
                        print(' Time: {} Device: {} \nName: {}'.format(timestamp,self.sensor_id[j,i],self.name[j,i]))
                        print("Value: {} ".format(s))
                        print("rtu Number of threads:",threading.active_count()) 
# Normal publishing when loopCount =5 i.e 5*5=25 sec
                        if(loopCount%12==0):

#Writing in the local database
                          if localdb.conn=='1':
                             try:
                               self.pub(timestamp,self.sensor_id[j,i],s,u1[j,i],self.name[j,i]) #publishing the data to aws mqtt
                               localdb().write_to_localdb(timestamp,self.sensor_id[j,i],s,u1[j,i],self.name[j,i],'1','1')
                               localdb().publish_to_mqtt()
                               print("written to localdb")
                               time.sleep(.2)
                             except:
                               print('Error 1')
                               pass
                          else:
                               localdb().write_to_localdb(timestamp,self.sensor_id[j,i],s,u1[j,i],self.name[j,i],'0','0')
                  last_val=new_val
                  time.sleep(delay_read)
    except KeyboardInterrupt:
          pass
    print('Exiting the loop')
    self.myAWSIoTMQTTClient.disconnect()
    print('Disconnected from AWS')
#modbus_rtu('AQ002Q52',[1432301,1432311],1,8,'E',19200,[400001,400001],[2,2],1,[0.05,.05],["C","C"],["Temperature","Temperature"])
