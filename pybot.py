"""
    Catbot (https://github.com/flyconnectome/catbot) is a Slack bot that interfaces with CATMAID and ZOTERO
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
    along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import time, re, threading, random, json, sys, subprocess
import matplotlib.pyplot as plt
import rpy2.robjects as robjects
from slackclient import SlackClient
from plotneuron import plotneuron
from pymaid import CatmaidInstance, get_review, get_3D_skeleton, retrieve_partners, retrieve_names, skid_exists
from tabulate import tabulate
from rpy2.robjects.packages import importr
from pyzotero import zotero
from datetime import datetime

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

		for s in skids:
			if skid_exists( s, remote_instance ) is False:
				response = "I'm sorry - the neuron #%s does not seem to exists. Please try again." % s
				self.slack_client.api_call("chat.postMessage", channel=self.channel,
	                          text=response, as_user=True)
				return

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
			for s in skids:
				if skid_exists( s, remote_instance ) is False:
					response = "I'm sorry - the neuron #%s does not seem to exists. Please try again." % s
					self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)
					return

			ts = self.slack_client.api_call("chat.postMessage", channel=self.channel,
									text='Got it! Generating plot - please wait...', as_user=True)['ts']

			fig, ax = plotneuron(skids, remote_instance, 'brain')
			if len(skids) > 1:
				plt.legend()
			plt.savefig( 'renderings/neuron_plot.png', transparent = False )

			self.slack_client.api_call(	"chat.delete",
										channel = self.channel,
										ts = ts
										)

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

class return_connectivity(threading.Thread):
	""" Class to process incoming connectivity requests
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

		for s in skids:
			if skid_exists( s, remote_instance ) is False:
				response = "I'm sorry - the neuron #%s does not seem to exists. Please try again." % s
				self.slack_client.api_call("chat.postMessage", channel=self.channel,
	                          text=response, as_user=True)
				return

		self.command = self.command.replace('”','"')

		try:
			thresh = int( re.search('threshold=(\d+)',self.command).group(1) )
		except:
			thresh = 1

		try:
			filt = re.search('filter="(.*?)"',self.command).group(1).split(',')
			print('Filtering partners for:', filt)
		except:
			filt = []

		if 'incoming' not in self.command and 'outgoing' not in self.command and 'upstream' not in self.command and 'downstream' not in self.command:
			directions = ['incoming','outgoing']
		elif 'incoming' in self.command or 'upstream' in self.command:
			directions = ['incoming']
		elif 'outgoing' in self.command or 'downstream' in self.command:
			directions = ['outgoing']

		if not skids:
			response = 'Please provide skids as *#skid*! For example: _plot-neuron #957684_'
		else:				
			cn = retrieve_partners( skids, remote_instance , threshold = thresh)
			neuron_names = retrieve_names( list( set( [ n for n in cn['incoming'] ] + [ n for n in cn['outgoing'] ] + skids ) ) , remote_instance )

			trunc_names = {}
			for n in neuron_names:
				if len( neuron_names[n] ) > 25:
					trunc_names[n] = neuron_names[n][:25] + '..'
				else:
					trunc_names[n] = neuron_names[n]

			response = 'Here are partners of the neuron(s):\n'

			for i,n in enumerate(skids):
				response += '%i: %s - #%s\n' % ( i, neuron_names[n], n )

			self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text=response, as_user=True)

			for d in directions:		
				response = '%s partners:\n' % d
				table = [ [ '*Name*','*Skid*'] + [ '*' + str(i) + '*' for i in range(len(skids)) ] ]

				#Order by connectivity strength
				n_max = { n: max( [ cn[d][n]['skids'][t] for t in cn[d][n]['skids'] ] ) for n in cn[d] }
				n_order = sorted( [ n for n in cn[d] ], key = lambda x:n_max[x], reverse = True  )

				for n in n_order:
					if filt and True not in [ t in neuron_names[n].lower() for t in filt ]:
						continue

					this_line = [ trunc_names[ n ], n ]
					for s in skids:
						if s in cn[ d ][n]['skids']:
							this_line.append( cn[ d ][n]['skids'][s] )
						else:
							this_line.append( 0 )
					table.append( this_line )								
				self.slack_client.api_call("chat.postMessage", channel=self.channel, text= response + '```' + tabulate(table) + '```', as_user=True)			

		return ''

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

		for s in skids:
			if skid_exists( s, remote_instance ) is False:
				response = "I'm sorry - the neuron #%s does not seem to exists. Please try again." % s
				self.slack_client.api_call("chat.postMessage", channel=self.channel,
	                          text=response, as_user=True)
				return

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

		ts = self.slack_client.api_call("chat.postMessage", channel=self.channel,
		                          text='Searching Zotero database. Please hold...', as_user=True)['ts']

		#Retrieve all items in library
		items = zot.everything ( zot.items() )
		pdf_files = [ i for i in items if i['data']['itemType'] == 'attachment' and i['data']['title'] == 'Full Text PDF' ]
		print('Searching %i Zotero items for:' % len(items))
		print(tags)

		self.slack_client.api_call(	"chat.delete",
										channel = self.channel,
										ts = ts
										)

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
		if 'partners' in self.command:
			response = '_partners_ returns the synaptic partners for a list of skids. You can pass me keywords to filter the list: \n'
			response += '1. Add _incoming_ or _outgoing_ to limit results to up- or downstream partners \n'
			response += '2. Add _filter="tag1,tag2"_ to filter results for neuron names (case-insensitive, non-intersecting)\n'
			response += '3. Add _threshold=3_ to filter partners for a minimum number of synapses\n'		
		elif 'nblast' in self.command:
			response = '_pnblast_ blasts the provided neuron against the flycircuit database. Use the following optional arguments to refine: \n'
			response += '1. Use _nomirror_ to prevent mirroring of neurons before nblasting (i.e. if cellbody is already on the flys left). \n'
			response += '2. Use _hits=N_ to return the top N hits in the 3D plot. Default is 3\n'		
		else:			
			functions = [
						'_review-status #SKID_ : give me a list of skids and I will tell you their review status',
						'_plot #SKID_ : give me a list of skids to plot',
						'_url #SKID_ : give me a list of skids and I will generate urls to their root nodes',
						'_nblast #SKID_ : give me a single skid and let me run an nblast search. Type _@catbot help nblast_ to learn more.',
						'_zotero TAG1 TAG2 TAG3_ : give me tags and I will search our Zotero group for you',
						'_zotero file ZOTERO-ID_ : give me a Zotero ID and I will download the PDF for you',
						'_partners #SKID_ : returns synaptic partners. Type _@catbot help partners_ to learn more.',
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

def parse_slack_output(slack_rtm_output, user_list):
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
                print('Message from', [ e['name'] for e in user_list['members'] if e['id'] == output['user'] ], ':', output['text'] )
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
	open_processes = []
	previous_open_threads = 0
	command = channel = None

	user_list = slack_client.api_call('users.list')
	#print('Users:', user_list)

	if slack_client.rtm_connect():
		print("Pybot connected and running!")
		while True:
			try:
				command, channel = parse_slack_output(slack_client.rtm_read(), user_list)
			except:
				print('Oops - Error parsing slack output %s' % str( datetime.now() ) )

			if command and channel:
				print( str( datetime.now() ), ': got a commmand in channel', channel, ':' , command ) 
				if len(open_threads)+len(open_processes) <= botconfig.MAX_PARALLEL_REQUESTS:	
						t = None										
						if 'help' in command:
							t = return_help(slack_client, command, channel)
						elif 'review-status' in command:							
							t = return_review_status(slack_client, command, channel)						
						elif 'plot' in command:
							t = return_plot_neuron(slack_client, command, channel)
						elif 'url' in command:
							t = return_url(slack_client, command, channel)
						elif 'partners' in command:
							t = return_connectivity(slack_client, command, channel)
						elif 'nblast' in command:
							#t = return_nblast(slack_client, command, channel)
							#For some odd reason, threading does not prevent freezing while waiting R code to return nblast results
							#Therfore nblasting is used as a fire and forget script by creating a new subprocess
							skids = re.findall('#(\d+)', command)
							if len(skids) == 1:								
								if skid_exists( skids[0], remote_instance ) is False:
										response = "I'm sorry - the neuron #%s does not seem to exists. Please try again." % skids[0]
										slack_client.api_call("chat.postMessage", channel=channel,
							                          text=response, as_user=True)
								else:										
									mirror = not 'nomirror' in command
									try:
										hits = int ( re.search('hits=(\d+)').group(1) )
									except:
										hits = 3

									p = subprocess.Popen("python3 ffnblast.py %s %s" % (skids[0],channel, mirror, hits ) , shell=True)
									open_processes.append(p)
							else:
								slack_client.api_call("chat.postMessage", channel=channel, text='I need a single skeleton ID to nblast! E.g. #123456', as_user=True)
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

			if len(open_threads)+len(open_processes) != previous_open_threads:				
				print('Open threads/processes:', len(open_threads)+len(open_processes))
				previous_open_threads = len(open_threads)+len(open_processes)

			#Try closing open threads
			if open_threads:
				for t in open_threads:
					if not t.is_alive():
						t.join()						
						open_threads.remove(t)

			if open_processes:
				for p in open_processes:
					if p.poll() is not None:
						open_processes.remove(p)

			time.sleep(botconfig.READ_WEBSOCKET_DELAY)
	else:
		print("Connection failed. Invalid Slack token or bot ID?")



