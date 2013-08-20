#!/usr/bin/env python
# -*- coding: utf8 -*-
import pyinotify
import argparse
import pylast
import os
import sys
import logging
from time import sleep
import simplejson

parser = argparse.ArgumentParser(description='A python script, that organizes your library in tags, using symlinks.\n\
https://github.com/mutantcornholio/librarymaker')
parser.add_argument('-r', '--rebuild', dest='REBUILD', action='store_true',\
				help='rescan existing library, not only watch for new items')
parser.add_argument('-c','--config-file', dest='CONFIG_PATH', default='~/.librarymakerrc.json',\
				help='choose a different location for a config file')

CONFIG_PATH = os.path.expanduser(parser.parse_args().CONFIG_PATH)
REBUILD = parser.parse_args().REBUILD

if not os.access(CONFIG_PATH, os.R_OK):
	if CONFIG_PATH==os.path.expanduser('~/.librarymakerrc.json'):
		sys.stderr.write('Can\'t work without a config file. Consider creating one in %s, \
or run me with --config-file argument\n' % os.path.expanduser('~/.librarymakerrc.json'))
	else:
		sys.stderr.write('%s: No such file or premission was denied\n' % CONFIG_PATH)
	exit()

try:
	config = simplejson.loads(open(CONFIG_PATH, 'r').read())
	WATCH_DIR=config['WATCH_DIR']
	DEST_DIR=config['DEST_DIR']
	LOG_FILE=config['LOG_FILE']
	IGNORE_LIST=config['IGNORE_LIST']
	RETRY_INTERVAL=float(config['RETRY_INTERVAL'])
	POPULARITY_THRESHOLD=float(config['POPULARITY_THRESHOLD'])
	COMPILATIONS=bool(config['COMPILATIONS'])
	API_KEY=config['API_KEY']
except simplejson.decoder.JSONDecodeError, e:
	sys.stderr.write('Something\'s wrong with your config file: %s. Exiting.\n' % e.message)
	exit()
except KeyError, e:
	sys.stderr.write('%s is missing in your config file. Exiting.\n' % e.message)
	exit()
except ValueError, e:
	sys.stderr.write('There\'s a problem in your config file: %s. Exiting.\n' % e.message)

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

network = pylast.LastFMNetwork(api_key = API_KEY)

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
					logging.warning('can\'t make directory, something\'s wrong, \
something\'s not quite right: %s' % os.path.join(WATCH_DIR,self.name))

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

    def process_IN_DELETE(self, event):
    	logging.info('%s has been deleted' % event.pathname)
    	for item in os.listdir(DEST_DIR):
    		item=os.path.join(DEST_DIR,item)
    		if os.path.isdir(item):
    			for item_inside in os.listdir(item):
    				item_inside=os.path.join(item,item_inside)
    				if os.path.islink(item_inside) and os.readlink(item_inside)==os.path.join(WATCH_DIR,event.pathname):
    					try:
    						os.unlink(item_inside)
    						logging.info('%s has been removed from %s' % (os.path.basename(event.pathname), os.path.basename(item)))
    					except Exception, e:
    						logging.error('Can\'t remove %s: %s' % (item_inside, e.message))        

def kill_zombie_musicians(folder):
	print folder
	for item in os.listdir(folder):
		item=os.path.join(folder, item)
		if os.path.islink(item) and not os.access(os.readlink(item),os.F_OK):
			print 'YEAH'
			os.unlink(item)
			logging.info('%s has been removed from %s' % (os.path.basename(item), os.path.basename(folder)))

def rebuild():
	for item in os.listdir(DEST_DIR):
		kill_zombie_musicians(os.path.join(DEST_DIR,item))
	artist_names = map(lambda s: s.decode('utf8',errors='ignore'), os.listdir(WATCH_DIR))
	artists=map(Artist, artist_names)
	for artist in artists:
		artist.tags_fetch()
		artist.tags_calculate()
		artist.make_ln()
		
logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', filename=LOG_FILE, level=logging.INFO)
watch_manager = pyinotify.WatchManager()
watching_events = pyinotify.IN_CREATE | pyinotify.IN_DELETE
handler=EventHandler()
notifier = pyinotify.Notifier(watch_manager, handler)
watch = watch_manager.add_watch(WATCH_DIR, watching_events, rec=False)

if REBUILD:
	rebuild()

notifier.loop()