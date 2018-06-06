#!/usr/bin/env python2.6
import jpype
from jpype import java
from jpype import javax

HOST='192.168.90.50'
PORT=9999
USER='admin'
PASS='mypass'

URL = "service:jmx:rmi:///jndi/rmi://%s:%d/jmxrmi" % (HOST, PORT)
#this it the path of your libjvm /usr/lib/jvm/sun-jdk-1.6/jre/lib/amd64/server/libjvm.so on linux
jpype.startJVM("/System/Library/Frameworks/JavaVM.framework/Libraries/libjvm_compat.dylib")
java.lang.System.out.println("JVM load OK")

jhash = java.util.HashMap()
jarray=jpype.JArray(java.lang.String)([USER,PASS])
jhash.put (javax.management.remote.JMXConnector.CREDENTIALS, jarray);
jmxurl = javax.management.remote.JMXServiceURL(URL)
jmxsoc = javax.management.remote.JMXConnectorFactory.connect(jmxurl,jhash)
connection = jmxsoc.getMBeanServerConnection();


object="java.lang:type=Threading"
attribute="ThreadCount"
attr=connection.getAttribute(javax.management.ObjectName(object),attribute)
print  attribute, attr

#Memory is a special case the answer is a Treemap in a CompositeDataSupport
object="java.lang:type=Memory"
attribute="HeapMemoryUsage"
attr=connection.getAttribute(javax.management.ObjectName(object),attribute)
print attr.contents.get("used")