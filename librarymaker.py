#!/usr/bin/env python
# -*- coding: utf8 -*-
WATCH_DIR = '/home/cornholio/sda1/music/.artists'
DEST_DIR = '/home/cornholio/sda1/music/test'
LOG_FILE = '/var/log/librarymaker.log'
IGNORE_LIST = [u'rock', u'instrumental', u'electronic', u'hard rock', u'alternative', u'icelandic', u'schlau machen']
RETRY_INTERVAL=2 #in seconds
POPULARITY_THRESHOLD = 0.4 #if *this * valid tag popularity is less than (first tag 
					#popularity)*POPULARITY_THRESHOLD, *this* and less popular ones do not count
COMPILATIONS = 'false' #if true, daemon works differently with directories
						#starting with "VA -". It looks for tags in files inside
						#the directory and count mean tags for entire compilation
						#(not implemented yet)


API_KEY = '94225c093fbb4a47e6f557af056baf20'
API_SECRET = ''

import pyinotify
import argparse
import pylast
import os
import sys
import logging
from time import sleep

if not os.path.isdir(WATCH_DIR):
	sys.stderr.write('%s do not exist or not a directory, exiting\n' % WATCH_DIR)
	exit()

if not os.path.isdir(DEST_DIR):
	sys.stderr.write('%s do not exist or not a directory, exiting\n' % DEST_DIR)
	exit()

if not os.access(DEST_DIR, os.W_OK):
	sys.stderr.write('you do not seem to have write rights to this destination directory: "%s", exiting \n' % DEST_DIR)
	exit()

if not os.access(LOG_FILE, os.W_OK):
	sys.stderr.write('you do not seem to have write rights to this log file: "%s", exiting \n' % LOG_FILE)
	exit()

network = pylast.LastFMNetwork(api_key = API_KEY, api_secret = API_SECRET)

class Tag(object):
	def __init__(self, name, weight):
		self.name = name
		self.weight = weight
		self.directory_okay = 0
	def make_dir(self):
		if os.access(os.path.join(DEST_DIR, self.name), os.F_OK):
			if not os.path.isdir(os.path.join(DEST_DIR, self.name))or not os.access(os.path.join(DEST_DIR, self.name), os.W_OK):
				logging.warning('%s is already exist, but it is not a directory \
or you don\'t have enough rights. Ignoring' % os.path.join(DEST_DIR, self.name))
				self.directory_okay = 0
			else:
				self.directory_okay = 1
		else:
			os.makedirs(os.path.join(DEST_DIR, self.name))
			self.directory_okay = 1
			logging.info('new tag: %s' % self.name)

class Artist(object):
	def __init__(self, name):
		self.name = name
		self.raw = pylast.Artist(name,network)
		self.valid_tags = []
	
	def tags_fetch(self):
		self.tags=[]
		while 1:	
			try:
				top_tags = self.raw.get_top_tags(limit=10)
				break
			except pylast.WSError as e:
				if e.details=='The artist you supplied could not be found':
					logging.info('no such artist in last.fm: "%s"' % self.name)
					self.tags.append(Tag(name='untagged',weight=100))
					return
				else:
					raise
			except pylast.NetworkError as e:
				logging.error('Network error')
				sleep(RETRY_INTERVAL)
		for tag in top_tags:
			self.tags.append(Tag(tag.item.name, int(tag.weight)))

	def tags_calculate(self):
		previous_weight=0
		for tag in self.tags:
			if tag.name in IGNORE_LIST:
				continue
			if previous_weight == 0:
				self.valid_tags.append(tag)
				previous_weight = tag.weight
			else:
				if tag.weight < previous_weight*POPULARITY_THRESHOLD:
					break
				else:
					self.valid_tags.append(tag)

	def make_ln(self):
		for tag in self.valid_tags:
			artist_dir = os.path.join(DEST_DIR,tag.name,self.name)
			if tag.directory_okay:
				os.symlink(os.path.join(WATCH_DIR,self.name),artist_dir)
				logging.info('artist %s was tagged as %s' % (self.name, tag.name))
			else:
				tag.make_dir()
				if tag.directory_okay:
					if not os.access(artist_dir, os.F_OK):
						os.symlink(os.path.join(WATCH_DIR,self.name),artist_dir)
						logging.info('artist %s was tagged as %s' % (self.name, tag.name))
					elif os.path.islink(artist_dir):
						if not os.path.samefile(os.readlink(artist_dir),os.path.join(WATCH_DIR,self.name)):
							logging.warning('%s is a symlink, but \
it is leading to %s instead of %s' % artist_dir, os.readlink(artist_dir), os.path.join(WATCH_DIR, self.name))
				else:
					logging.warning('can\'t make directory, something\'s wrong, something\'s not quite right: %s' % os.path.join(WATCH_DIR,self.name))

class VA(object):
	def __init__(self, name):
		self.name = name

class EventHandler(pyinotify.ProcessEvent):
    def process_IN_CREATE(self, event):
    	if os.path.isdir(event.pathname):
    		artist=Artist(os.path.basename(event.pathname))
    		artist.tags_fetch()
    		artist.tags_calculate()
    		artist.make_ln()
    	else:
    		logging.info('%s appeared, but it is not a directory. Ignoring.' % os.path.basename(event.pathname))
        
def rebuild():
	artist_names = map(lambda s: s.decode('utf8',errors='ignore'), os.listdir(WATCH_DIR))
	artists=map(Artist, artist_names)
	for artist in artists:
		artist.tags_fetch()
		artist.tags_calculate()
		artist.make_ln()
		
logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', filename=LOG_FILE, level=logging.INFO)
watch_manager = pyinotify.WatchManager()
watching_events = pyinotify.IN_CREATE
handler=EventHandler()
notifier = pyinotify.Notifier(watch_manager, handler)
watch = watch_manager.add_watch(WATCH_DIR, watching_events, rec=False)

notifier.loop()