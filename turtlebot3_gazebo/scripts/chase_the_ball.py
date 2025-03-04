#!/usr/bin/env python

import sys
import time
import cv2
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image, CompressedImage
from geometry_msgs.msg import Twist
import rospy
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
import threading
import numpy as np

CNT = 0


class BufferQueue(Queue):
    """Slight modification of the standard Queue that discards the oldest item
    when adding an item and the queue is full.
    """
    def put(self, item, *args, **kwargs):
        # The base implementation, for reference:
        # https://github.com/python/cpython/blob/2.7/Lib/Queue.py#L107
        # https://github.com/python/cpython/blob/3.8/Lib/queue.py#L121
        with self.mutex:
            if self.maxsize > 0 and self._qsize() == self.maxsize:
                self._get()
            self._put(item)
            self.unfinished_tasks += 1
            self.not_empty.notify()

class cvThread(threading.Thread):
    """
    Thread that displays and processes the current image
    It is its own thread so that all display can be done
    in one thread to overcome imshow limitations and
    https://github.com/ros-perception/image_pipeline/issues/85
    """
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.queue = queue
        self.image = None

        # Initialize published Twist message
        self.cmd_vel = Twist()
        self.cmd_vel.linear.x = 0
        self.cmd_vel.angular.z = 0
        

    def run(self):
        # Create a single OpenCV window
        cv2.namedWindow("frame", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("frame", 800,600)

        while True:
            self.image = self.queue.get()

            # Process the current image
            mask, contour, crosshair = self.processImage(self.image)

            # Add processed images as small images on top of main image
            result = self.addSmallPictures(self.image, [mask, contour, crosshair])
            cv2.imshow("frame", result)

            # Check for 'q' key to exit
            k = cv2.waitKey(6) & 0xFF
            if k in [27, ord('q')]:
                rospy.signal_shutdown('Quit')
    
    def processImage(self, img):
        global CNT
        rows,cols = img.shape[:2]
        
        R,G,B = self.convert2rgb(img)

        redMask = self.thresholdBinary(R, (220, 255))
        stackedMask = np.dstack((redMask, redMask, redMask))
        contourMask = stackedMask.copy()
        crosshairMask = stackedMask.copy()

        # return value of findContours depends on OpenCV version
        (_, contours,hierarchy) = cv2.findContours(redMask.copy(), 1, cv2.CHAIN_APPROX_NONE)

        # Find the biggest contour (if detected)
        if len(contours) > 0:
            CNT=0
            c = max(contours, key=cv2.contourArea)
            M = cv2.moments(c)

            # Make sure that "m00" won't cause ZeroDivisionError: float division by zero
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
            else:
                cx, cy = 0, 0
		
	        

            # Show contour and centroid
            cv2.drawContours(contourMask, contours, -1, (0,255,0), 10)
            cv2.circle(contourMask, (cx, cy), 5, (0, 255, 0), -1)



            # Show crosshair and difference from middle point
            cv2.line(crosshairMask,(cx,0),(cx,rows),(0,0,255),10)
            cv2.line(crosshairMask,(0,cy),(cols,cy),(0,0,255),10)
            cv2.line(crosshairMask,(int(cols/2),0),(int(cols/2),rows),(255,0,0),10)

	    for i in range (len(contours)):
   		    equi_diameter = cv2.minEnclosingCircle(contours[i])[1]
            
	    equi_diameter = int(equi_diameter)
	    print("Ballon rouge de diametre "+str(equi_diameter)+"mm detecte !")
            print(" Je me rapproche de celui-ci !")

            # Chase the ball
            #print(abs(cols - cx), cx, cols)

            if equi_diameter > 150:
                self.cmd_vel.linear.x = 0
                self.cmd_vel.angular.z = 0
                pub.publish(self.cmd_vel)
                print("\n\n J\'ai trouve votre ballon de basket et je suis arrive devant !")
                print("Il ne reste plus qu'a le ramasser.")
                exit(0)
                
                

            elif abs(cols/2 - cx) > 20:
                self.cmd_vel.linear.x = 0
                if cols/2 > cx:
                    self.cmd_vel.angular.z = 0.2
                else:
                    self.cmd_vel.angular.z = -0.2

            else:
                self.cmd_vel.angular.z = 0
                self.cmd_vel.linear.x = 0.4

        else:
            
            self.cmd_vel.linear.x = 0
            self.cmd_vel.angular.z = 1
            global start

            if CNT==0:
                start = time.time()
            print("Recherche de ballon rouge en cours...")
            end = time.time()
            diff = 25-(end - start)
            print("Temps restant : "+str(diff))

            if diff<=0:
                self.cmd_vel.linear.x = 0
                self.cmd_vel.angular.z = 0
                pub.publish(self.cmd_vel)
                print("\n\n Votre ballon de basket est introuvable sorry")
                print("(Relancer le script pour effectuer une autre recherche)\n\n")
                exit(0)
                

            CNT=1

        # Publish cmd_vel
        pub.publish(self.cmd_vel)

        # Return processed frames
        return redMask, contourMask, crosshairMask

    # Convert to RGB channels
    def convert2rgb(self, img):
        R = img[:, :, 2]
        G = img[:, :, 1]
        B = img[:, :, 0]

        return R, G, B

    # Apply threshold and result a binary image
    def thresholdBinary(self, img, thresh=(200, 255)):
        binary = np.zeros_like(img)
        binary[(img >= thresh[0]) & (img <= thresh[1])] = 1

        return binary*255

    # Add small images to the top row of the main image
    def addSmallPictures(self, img, small_images, size=(160, 120)):
        '''
        :param img: main image
        :param small_images: array of small images
        :param size: size of small images
        :return: overlayed image
        '''

        x_base_offset = 40
        y_base_offset = 10

        x_offset = x_base_offset
        y_offset = y_base_offset

        for small in small_images:
            small = cv2.resize(small, size)
            if len(small.shape) == 2:
                small = np.dstack((small, small, small))

            img[y_offset: y_offset + size[1], x_offset: x_offset + size[0]] = small

            x_offset += size[0] + x_base_offset

        return img

def queueMonocular(msg):
    try:
        # Convert your ROS Image message to OpenCV2
        cv2Img = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    except CvBridgeError as e:
        print(e)
    else:
        qMono.put(cv2Img)

print("OpenCV version: %s" % cv2.__version__)

queueSize = 1      
qMono = BufferQueue(queueSize)

cvThreadHandle = cvThread(qMono)
cvThreadHandle.setDaemon(True)
cvThreadHandle.start()

bridge = CvBridge()

rospy.init_node('ball_chaser')
# Define your image topic
image_topic = "/camera/rgb/image_raw"
# Set up your subscriber and define its callback
rospy.Subscriber(image_topic, Image, queueMonocular)

pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
# Spin until Ctrl+C
rospy.spin()
