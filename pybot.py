"""
    Pybot is a Slack bot that interfaces with CATMAID and ZOTERO
    Copyright (C) 2017 Philipp Schlegel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import time, re, threading, random, json, sys
import matplotlib.pyplot as plt
import rpy2.robjects as robjects
from slackclient import SlackClient
from plotneuron import plotneuron
from pymaid import CatmaidInstance, get_review, get_3D_skeleton
from tabulate import tabulate
from rpy2.robjects.packages import importr
from pyzotero import zotero

class return_review_status(threading.Thread):
	""" Class to process incoming review-status request
    """
	def __init__(self, slack_client ,command,channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None

	def run(self):
		""" Extracts skids from command and returns these neurons review-status.
		"""	
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )
		skids = re.findall('#(\d+)',self.command)
		if not skids:
			response = 'Please provide skids as *#skid*! For example: _@catbot review-status #957684_'
		else:
			r_status = get_review (skids, remote_instance = remote_instance)
			response = 'This is the current review status: ```'
			for s in r_status:
				response += '\n #%s: %i %%' % (s, int(r_status[s][1]/r_status[s][0] * 100) )
			response += '```'

		if response:
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)

		return
	
class return_plot_neuron(threading.Thread):
	""" Class to process incoming plot neuron request
    """
	def __init__(self, slack_client ,command,channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None

	def run(self):
		""" Extracts skids from command and generates + uploads a file
		"""
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )
		skids = re.findall('#(\d+)',self.command)

		if not skids:
			response = 'Please provide skids as *#skid*! For example: _@catbot plot-neuron #957684_'
		else:		
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
									text='Got it! Generating plot - please wait...', as_user=True)
			fig, ax = plotneuron(skids, remote_instance)
			if len(skids) > 1:
				plt.legend()
			plt.savefig( 'renderings/neuron_plot.png', transparent = False )

			with open('renderings/neuron_plot.png', 'rb') as f:
				self.slack_client.api_call("files.upload", 	channels=self.channel, 
														file = f,
														title = 'Neuron plot',
														initial_comment = 'Neurons #%s' % ' #'.join(skids)
														 )

			response = ''

		if response:
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)
		return 

class return_url(threading.Thread):
	""" Class to process incoming url to neuron request
    """
	def __init__(self, slack_client ,command,channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None

	def run(self):
		""" Returns urls for a list of neurons
		"""		
		skids = re.findall('#(\d+)',self.command)
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )

		if not skids:
			response = 'Please provide skids as *#skid*! For example: _plot-neuron #957684_'
		else:	
			response = 'Here are URLs to the neurons you have provided!'
			skdata = get_3D_skeleton( skids, remote_instance , connector_flag = 0, tag_flag = 0, get_history = False, time_out = None, silent = True)
			for i, neuron in enumerate(skdata):
				root = [n for n in neuron[0] if n[1] == None][0]
				url = remote_instance.url_to_coordinates( 1 , root[3:6] , stack_id = 8, tool = 'tracingtool' , active_skeleton_id = skids[i], active_node_id = root[0] )
				response += '\n *#%s*: %s' % ( skids[i], url )

		if response:
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)

		return response

class return_zotero(threading.Thread):
	""" Class to process requests to access zotero
	"""
	def __init__(self, slack_client ,command,channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None		

	def run(self):
		""" Lists all available commands and their syntax.
		"""
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )		

		#First extract tags to search for
		command = self.command.replace('zotero', '')
		tags = command.split(' ')

		if '' in tags:
			tags.remove('')

		#Retrieve all items in library
		items = zot.items()
		pdf_files = [ i for i in items if i['data']['itemType'] == 'attachment' and i['data']['title'] == 'Full Text PDF' ]
		print('Searching %i Zotero items for:' % len(items))
		print(tags)

		if 'file' in tags:
			dl_file = True
			tags.remove('file')
			if len(tags) > 1:
				self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text='If you want me to grab you a PDF, please give me a single zotero key: _@catbot zotero file ZOTERO-ID_', as_user=True)
			elif len(tags) == 1:				
				this_item = [ f for f in pdf_files if f['data']['parentItem'].lower() == tags[0] ]

				if this_item:				
					filename = this_item[0]['data']['filename']
					zot.dump( this_item[0]['key'] , filename )
					with open( filename , 'rb') as f:
						self.slack_client.api_call("files.upload", 	channels=self.channel, 
																file = f,
																title = filename,
																initial_comment = ''
																)
					return
				else:
					self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text="Oops! I can't seem to find a PDF to the Zotero key you have given me...", as_user=True)
					return

		else:
			dl_file = False

		results = []

		for e in items:
			include = []	
			for t in tags:				
				this_tag = False
				#Try/Except is important because some entries aren't articles				
				try:
					if t in e['data']['date']:
						this_tag = True
						#print('Found tag %s in %s' % ( t, e['data']['date'] ) )
					elif t.lower() in [ a['lastName'].lower() for a in e['data']['creators']]:
						this_tag = True	
						#print('Found tag %s in %s' % ( t, str([ a['lastName'].lower() for a in e['data']['creators']]) ) )
					elif t.lower() in e['data']['title'].lower():
						this_tag = True
						#print('Found tag %s in %s' % ( t, e['data']['title'].lower() ) )
					elif True in [ t.lower() in a['tag'].lower() for a in e['data']['tags'] ]:
						this_tag = True
						#print('Found tag %s in %s (%s)' % ( t, [ a['tag'].lower() for a in e['data']['tags'] ], [ t.lower() in a['tag'].lower() for a in e['data']['tags'] ] ) )
				except:
					pass
				
				#print('After:',this_tag)
				include.append( this_tag )

			if False not in include:
				#print(tags, include, e['data']['date'] )
				results.append( e )

		if results:
			response = 'Here are the publications matching your criteria:\n```'	
			response += 'Author\tJournal\tDate\tTitle\tDOI\tUrl\t(Zotero ID)\n'	
			for e in results:
				try:
					doi_url = '- http://dx.doi.org/' + e['data']['DOI']
				except:
					doi_url = ''

				authors = [ a['lastName'] for a in e['data']['creators'] ]
				date = e['data']['date']
				journal = e['data']['journalAbbreviation']
				title = e['data']['title']
				zot_key = e['key']


				if len(e['data']['creators']) > 2:			
					response += '%s et al., %s (%s): %s %s (%s)\n\n' % ( authors[0], journal, date, title , doi_url, zot_key  )
				elif len(e['data']['creators']) == 2:			
					response += '%s and %s, %s (%s): %s %s (%s)\n\n' % ( authors[0], authors[1] , journal, date, title , doi_url, zot_key   )
				elif len(e['data']['creators']) == 1:			
					response += '%s, %s (%s): %s %s (%s)\n\n' % ( authors[0], journal, date, title , doi_url, zot_key  )
			response += '```\n'
			response += 'Use _@catbot zotero file ZOTERO-ID_ if you want me to grab you the PDF!'
		else:
			response = 'Sorry, I could not find anything matching your criteria!'

		self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)

		return 

class return_help(threading.Thread):
	""" Class to process incoming help request
    """
	def __init__(self, slack_client ,command,channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None		

	def run(self):
		""" Lists all available commands and their syntax.
		"""
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )
		functions = [
					'_review-status #SKID_ : give me a list of skids and I will tell you their review status',
					'_plot #SKID_ : give me a list of skids to plot',
					'_url #SKID_ : give me a list of skids and I will generate urls to their root nodes',
					'_nblast #SKID_ : give me a single skid and let me run an nblast search',
					'_zotero TAG1 TAG2 TAG3_ : give me tags and I will search our Zotero group for you_',
					'_zotero file ZOTERO-ID_ : give me a Zotero ID and I will download the PDF for you_',
					'_help_ : I will tell you what I am capable of'
					]

		response = 'Currently I can help you with the following commands:'
		for f in functions:
			response += '\n' + f
		response += '\n skids have to start with a # (hashtag), separate multiple arguments by space'


		if response:
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)
		return 

class return_nblast( threading.Thread ):
	""" Class to process incoming nblast request
	"""
	def __init__(self, slack_client , command, channel):
		try:
			self.command = command
			self.channel = channel
			self.slack_client = slack_client
			self.id = random.randint(1,99999)
			threading.Thread.__init__(self)			           
		except:
			print('!Error initiating thread for',self.command)  

	def join(self):
		try:
			threading.Thread.join(self)
			print('Thread %i closed' % self.id )
			return None
		except:
			print('!ERROR joining thread for',self.url)
		return None

	def run(self):
		""" Returns nblast results for a given neuron
		"""
		print('Started new thread %i for command <%s>' % (self.id, self.command ) )
		skids = re.findall('#(\d+)',self.command)

		if len(skids) == 1:
			self.slack_client.api_call("chat.postMessage", channel=self.channel, text='Blasting neuron %s - please wait...' % skids[0], as_user=True)		

			results, summary = self.nblast_neuron(skids[0], mirror = True, reverse = False)

			table = [ ['*Name*','*Score*','*MuScore*','*Driver*','*Gender*' ] ]		

			for r in summary:				
				table.append ( [ r['name'], round(r['score'],3) , round(r['muscore'],3) , r['Driver'], r['Gender'] ] )			

			self.slack_client.api_call("chat.postMessage", channel=self.channel, text= '```'+tabulate(table)+'```', as_user=True)

			with open('webGL/index.html', 'rb') as f:
				self.slack_client.api_call("files.upload", 	channels=self.channel, 
														file = f,
														title = '3D nblast results for neuron #%s' % skids[0],
														initial_comment = 'Open file in browser'
														)
			response = ''		
		else:
			response = 'Please provide a single skeleton ID. For example _@catbot nblast #957684_'

		if response:
			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)
		return 	
	

	def nblast_neuron(self, skid, mirror = True, reverse = False):
		""" Uses rpy2 to interface with R nat and elmr packages to nblast a neuron from CATMAID server

		Returns:
		--------	
		generates webGL/index.html containing a webGL of the top hits
		s :		dict containing a summary of nblast results
				{ 'score': [], 'muscore': [], 'ntype': [], 'glom': [], 'Driver': [], 'Gender': [], 'n': [] }
		r :		dict containing scores and transformed CATMAID neuron
				{ 	'sc' : { line_name: score }
					'scr' : { line_name: score }
					'n' : {
						'connectors': {'x': , 'connector_id': , 'treenode_id':, 'prepost':, 'x':, 'y':, 'z':}
						'headers':
						'EndPoints':
						'url':
						'SegList':
						'NumPoints':
						'tags':
						'NumSegs':
						'BranchPoints':
						'd':
						'nTrees':
						'StartPoint':
				 	}
				}
		"""

		elmr = importr('elmr')
		fc = importr('flycircuit')		
		domc = importr('doMC')
		cores = robjects.r('registerDoMC(8)')
		rjson = importr('rjson')
		
		login = robjects.r('options(catmaid.server="%s", catmaid.authname="%s",catmaid.authpassword="%s", catmaid.token="%s")' % ( botconfig.SERVER_URL, botconfig.HTTP_USER, botconfig.HTTP_PW, botconfig.AUTHTOKEN ) )
		dps = robjects.r('dps<-read.neuronlistfh("http://flybrain.mrc-lmb.cam.ac.uk/si/nblast/flycircuit/dpscanon.rds",	localdir=getOption("flycircuit.datadir"))')
		#robjects.r('remotesync(dps,download.missing = TRUE)')
		robjects.r("options('nat.default.neuronlist'='dps')")

		nblast_fafb = robjects.r( 'nblast_fafb' )
		summary = robjects.r('summary')
		toJSON = robjects.r('toJSON')
		row_names = robjects.r('row.names')

		print('Blasting - please wait...')				
		res = nblast_fafb( int(skid), mirror = mirror, reverse = reverse )
		su = summary( res )	
		print('Done!')

		#Read results into python data objects
		s = []
		for i, c in enumerate( list( row_names( su ) ) ):
			s.append( { 
						'name': c,
						'score': su[0][i], 
						'muscore': su[1][i], 
						'ntype': su[2][i], 
						'glom': su[3][i], 
						'Driver': su[4][i],
						'Gender': su[5][i],
						'n': su[6][i]
					} )

		r = json.loads ( toJSON(res)[0] )

		#Generate a 3d html from the results
		plot3d = robjects.r( 'plot3d')
		writeWebGL = robjects.r( 'writeWebGL' )
		plot3d( res , hits = robjects.IntVector( range(3) ) )
		writeWebGL( 'webGL', width = 1000 )
		robjects.r('rgl.close()')

		return r , s

def parse_slack_output(slack_rtm_output):
    """
        The Slack Real Time Messaging API is an events firehose.
        this parsing function returns None unless a message is
        directed at the Bot, based on its ID.
    """
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and botconfig.AT_BOT in output['text']:
                # return text after the @ mention, whitespace removed
                return output['text'].split(botconfig.AT_BOT)[1].strip().lower(), \
                       output['channel']
    return None, None


if __name__ == '__main__':
	#botconfig.py holds credentials for CATMAID, Slack and Zotero
	try:
		import botconfig
	except:
		print('Import of botconfig.py failed. Please make sure you have this configuration file correctly set up!')
		sys.exit()

	#Initialize CATMAID instance
	remote_instance = CatmaidInstance( botconfig.SERVER_URL, botconfig.HTTP_USER, botconfig.HTTP_PW, botconfig.AUTHTOKEN )

	#Inintialize slack client
	slack_client = SlackClient( botconfig.SLACK_KEY )

	if botconfig.ZOT_KEY:
		# Zotero( group_id, library_type, API_key )
		zot = zotero.Zotero(botconfig.ZOT_GRP_ID,'group', botconfig.ZOT_KEY )
	else:
		zot = None

	open_threads = []
	previous_open_threads = 0

	if slack_client.rtm_connect():
		print("Pybot connected and running!")
		while True:
			try:
				command, channel = parse_slack_output(slack_client.rtm_read())
			except:
				print('Oops - Error parsing slack output')

			if command and channel:
				print('Got a commmand in channel', channel, ':' , command ) 
				if len(open_threads) <= botconfig.MAX_PARALLEL_REQUESTS:	
						t = None										
						if 'review-status' in command:							
							t = return_review_status(slack_client, command, channel)
						elif 'help' in command:
							t = return_help(slack_client, command, channel)
						elif 'plot' in command:
							t = return_plot_neuron(slack_client, command, channel)
						elif 'url' in command:
							t = return_url(slack_client, command, channel)
						elif 'nblast' in command:
							t = return_nblast(slack_client, command, channel)
						elif 'zotero' in command:
							if zot:
								t = return_zotero(slack_client, command, channel)
							else:
								response = "Sorry, I can't process your Zotero request unless you have it properly configured :("
								slack_client.api_call("chat.postMessage", channel=channel, text=response, as_user=True)
						else:
							response = "Not sure what you mean. Type _@catbot help_ to get a list of things I can do for you."
							slack_client.api_call("chat.postMessage", channel=channel, text=response, as_user=True)

						if t:
							t.start()
							open_threads.append( t )

				else:
					slack_client.api_call("chat.postMessage", channel=channel, text= 'I am currently really busy. Please give me a moment and try again. Cheers!', as_user=True )

			if len(open_threads) != previous_open_threads:				
				print('Open threads:', len(open_threads))
				previous_open_threads = len(open_threads)

			#Try closing open threads
			if open_threads:
				for t in open_threads:
					if not t.is_alive():
						t.join()						
						open_threads.remove(t)

			time.sleep(botconfig.READ_WEBSOCKET_DELAY)
	else:
		print("Connection failed. Invalid Slack token or bot ID?")



