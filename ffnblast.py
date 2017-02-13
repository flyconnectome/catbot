"""
	Fire and forget nblasting
	ffnblast.py is part of Catbot (https://github.com/flyconnectome/catbot) 
	Copyright (C) 2017 Philipp Schlegel

	Call from shell or using subprocess.Popen('python ffnblast <skid> <channel>')
	Will post results in slack channel and upload a webGL file containg the first 3 hits.

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

import rpy2.robjects as robjects
from rpy2.robjects.packages import importr
import json
from tabulate import tabulate
from slackclient import SlackClient

if __name__ == '__main__':
	import sys
	import botconfig	

	#Skid of the neuron to NBLAST and Slack channel to post the response to have to be passed as arguments
	skid = sys.argv[1] 
	channel = sys.argv[2]
	mirror = True 
	reverse = False

	#Initialize slack client from botconfig.py
	slack_client = SlackClient( botconfig.SLACK_KEY )
	#print('Connection to Slack:', slack_client.rtm_connect() )

	#Import R libraries
	elmr = importr('elmr')
	fc = importr('flycircuit')		
	domc = importr('doMC')
	cores = robjects.r('registerDoMC(8)')
	rjson = importr('rjson')

	#Make sure variables for databases are set correctly
	login = robjects.r('options(catmaid.server="%s", catmaid.authname="%s",catmaid.authpassword="%s", catmaid.token="%s")' % ( botconfig.SERVER_URL, botconfig.HTTP_USER, botconfig.HTTP_PW, botconfig.AUTHTOKEN ) )
	dps = robjects.r('dps<-read.neuronlistfh("http://flybrain.mrc-lmb.cam.ac.uk/si/nblast/flycircuit/dpscanon.rds",	localdir=getOption("flycircuit.datadir"))')
	#robjects.r('remotesync(dps,download.missing = TRUE)')
	robjects.r("options('nat.default.neuronlist'='dps')")

	#Make R functions callable in Python
	nblast_fafb = robjects.r( 'nblast_fafb' )
	summary = robjects.r('summary')
	toJSON = robjects.r('toJSON')
	row_names = robjects.r('row.names')

	print('Blasting - please wait...')	

	#print( 'flycircuit db path:' ,str( robjects.r('getOption("flycircuit.datadir")') ) )
	#print( 'flycircuit scoremat:' ,str( robjects.r('getOption("flycircuit.scoremat")') ) )
	#print( 'Nat neuronlist:' ,str( robjects.r('getOption("nat.default.neuronlist")') ) )

	res = nblast_fafb( int(skid), mirror = mirror, reverse = reverse )	
	su = summary( res )	

	#Read results into python data objects
	#summary = dict( zip( su.names, map( list, list( su ) ) ) )	
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

	results = json.loads ( toJSON(res)[0] )

	#Generate a 3d html from the results
	plot3d = robjects.r( 'plot3d')
	writeWebGL = robjects.r( 'writeWebGL' )
	plot3d( res , hits = robjects.IntVector( range(3) ) )
	writeWebGL( 'webGL', width = 1000 )
	robjects.r('rgl.close()')

	print('Finished nblasting neuron', skid )

	table = [ ['*Name*','*Score*','*MuScore*','*Driver*','*Gender*' ] ]	

	for e in s:				
		table.append ( [ e['name'], round(e['score'],3) , round(e['muscore'],3) , e['Driver'], e['Gender'] ] )			

	slack_client.api_call("chat.postMessage", channel=channel, text= '```'+tabulate(table)+'```', as_user=True)

	with open('webGL/index.html', 'rb') as f:
		slack_client.api_call("files.upload", 	channels=channel, 
												file = f,
												title = '3D nblast results for neuron #%s' % skid,
												initial_comment = 'Open file in browser'
												)