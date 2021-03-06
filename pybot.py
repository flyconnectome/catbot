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

import matplotlib
#Switch a non-interactive, PNG-only backend. On Linux Tkinter, the default backend, causes trouble.
matplotlib.use('AGG')
#Pyplot has to imported AFTER setting the backend!
import matplotlib.pyplot as plt

import time, re, threading, random, json, sys, subprocess, shelve, os
import rpy2.robjects as robjects
import logging
from slackclient import SlackClient
from tabulate import tabulate
from rpy2.robjects.packages import importr
from pyzotero import zotero
from datetime import datetime, date, timedelta
from websocket import WebSocketConnectionClosedException

import pymaid
from pymaid.plotting import plot2d
from pymaid import (CatmaidInstance,
                    get_review,
                    get_neuron,
                    get_partners,
                    get_names,
                    neuron_exists,
                    get_skids_by_name,
                    get_skids_by_annotation,
                    get_annotations,
                    url_to_coordinates,
                    eval_skids)


class subscription_manager(threading.Thread):
    """ Class to process subscriptions to neurons
    """

    def __init__(self, slack_client, command, channel, user, global_update = False):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.global_update = global_update
            self.user = user
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command, exc_info = True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url, exc_info = True  )
        return None

    def process_neurons( self, skids ):
        """
        Retrieves data for neurons from the CATMAID server and extracts relevant information

        Parameters:
        ----------
        skids :     skeleton IDs to check

        Returns:
        -------
        changes :   {skid: { value : [ old, new ] }}
        skdata :    skeleton data for all neurons (order as in <skids>)
        """

        #Retrieve relevant data from Catmaid server
        skdata = get_neuron(skids, remote_instance=remote_instance)
        connectivity = get_partners(skids, remote_instance=remote_instance,
                                    min_size = 500)
        annotations = get_annotations(skids, remote_instance=remote_instance)
        r_status = get_review(skids, remote_instance=remote_instance).set_index('skeleton_id')

        new_data = {}
        logger.info('Extracting data...')
        #Extract data
        for neuron in skdata.itertuples():
            if 'ends' in neuron.tags:
                closed_ends  =  len( neuron.tags['ends'] )
            else:
                closed_ends = 0

            if 'uncertain_ends' in neuron.tags:
                uncertain_ends  =  len( neuron.tags['uncertain_end'] )
            else:
                uncertain_ends = 0

            open_ends = neuron.nodes[ neuron.nodes.type == 'end' ].shape[0] - closed_ends - uncertain_ends

            try:
                this_an = annotations[ str(s) ]
            except:
                this_an = []

            #First collect all synaptically connected neurons
            all_con = {  n :  { 'upstream' : '-', 'downstream' : '-' }  for n in connectivity[ connectivity[ neuron.skeleton_id ] > 0 ].skeleton_id.unique() }

            for n in connectivity[ connectivity[ neuron.skeleton_id ] > 0 ][ [ 'skeleton_id', 'relation', neuron.skeleton_id ]  ].itertuples():
                all_con[ n.skeleton_id] [  n.relation ] = n[ 2 ]

            #Don't forget to update basic_values when editing database entries!
            new_data[ neuron.skeleton_id ] = {  'name'                  : neuron.neuron_name,
                                                'branch_points'         : neuron.nodes[ neuron.nodes.type == 'branch' ].shape[0],
                                                'n_nodes'               : neuron.nodes.shape[0],
                                                'pre_synapses'          : neuron.connectors[ neuron.connectors.relation == 0 ].shape[0],
                                                'post_synapses'         : neuron.connectors[ neuron.connectors.relation == 1 ].shape[0],
                                                'open_ends'             : open_ends,
                                                'synaptic_partners'     : all_con,
                                                'last_update'           : str( date.today() ),
                                                'last_edited_by'        : 'unknown',
                                                'annotations'           : this_an,
                                                'review_status'         : r_status.ix[ neuron.skeleton_id ].percent_reviewed
                                            }

        return new_data, skdata

    def run(self):
        """
        Structure of subscription database:

        { 'users': {
            'user_id'   : {

                                    'subscriptions': [ neuronA, neuronB, neuronC ] ,
                                    'daily_updates' : True/False,
                                    'neurons'       : { skid: {
                                                            'name' : str(),
                                                            'branch_points'         : int(),
                                                            'n_nodes'               : inte(),
                                                            'pre_synapses'          : int(),
                                                            'post_synapses'         : int(),
                                                            'open_ends'             : int(),
                                                            'upstream_partners'     : { skid: n_synapses },
                                                            'downstream_partners'   : { skid: n_synapses },
                                                            'last_update'           : timestamp_of_last_update,
                                                            'last_edited_by'        : user_id,
                                                            'annotations'           : list(),
                                                            'review_status'         : int()
                                                            }
                                                        }
            }
        }
        """
        basic_values = ['name','branch_points','n_nodes','pre_synapses','post_synapses','open_ends', 'review_status']

        logger.info('Started new thread %i for command <%s> by user <%s>' % (self.id, self.command, self.user ) )

        try:
            data = shelve.open('subscriptiondb')
        except:
            if self.user != None:
                self.slack_client.api_call("chat.postMessage", channel='@' + self.user,
                                      text='Unable to open subscription database!', as_user=True)
            else:
                logger.error('Unable to open subscription database.')
            return

        skids = parse_neurons( self.raw_command )

        #If db is fresh:
        if len(data) == 0:
            data['users'] = {}

        #If user not yet in database, add entry
        if self.user not in data['users'] and self.user != None:
            #Have to do this explicitedly - otherwise shelve won't update
            users = data['users']
            users[self.user] = {    'subscriptions' : [],
                                    'daily_updates' : True,
                                    'neurons': {} }
            data['users'] = users

        #Now execture user command
        if 'list' in self.command:
            #List current subscriptions
            neuron_names = get_names(data['users'][self.user]['subscriptions'],
                                     remote_instance=remote_instance)
            if neuron_names:
                response = 'You are currently subscribed to the following neurons: \n'
                response += '```' + tabulate( [ (neuron_names[str(s)], '#'+str(s) ) for s in data['users'][self.user]['subscriptions'] ] ) + '```'
            else:
                response = 'Currently, I do not have any subscriptions for you!'
        if 'new' in self.command:
            #Add new subscriptions
            if skids:
                new_data, skdata = self.process_neurons( [ str(s) for s in skids if s not in data['users'][self.user]['neurons'] ]  )

                users = data['users']
                users[self.user]['subscriptions'] += skids
                users[self.user]['subscriptions'] = list ( set( users[self.user]['subscriptions'] ) )
                data['users'] = users

                old_data = data['users']
                old_data[self.user]['neurons'].update( new_data )
                data['users'] = old_data

                response = 'Thanks! I have subscribed you to `' + ' #'.join( [ str(s )for s in skids ] ) + '`'
            else:
                response = 'Please give me at least a single neuron to subscribe you to!'
        if 'auto' in self.command:
            users = data['users']
            #Switch
            users[self.user]['daily_updates'] = users[self.user]['daily_updates'] == False
            data['users'] = users

            if data['users'][self.user]['daily_updates'] is True:
                response = 'Thanks! You will now automatically receive daily updates for your subscribed neurons.'
            else:
                response = 'Thanks! You will no longer receive daily updates.'

        if 'delete' in self.command:
            #Delete subscriptions
            if skids:
                response = 'Thanks! I succesfully unsubscribed you from neuron(s) ```'
                for s in skids:
                    try:
                        users = data['users']
                        users[self.user]['subscriptions'].remove( s )
                        data['users'] = users
                        response += +'#' + str(s) + ' '
                    except:
                        pass
                response += '```'
            else:
                response = 'Please provide me at least a single neuron to subscribe you to!'

        #IDEA: PRINT CHANGES (+100, -100) instead of new/old?
        #ADD CHANGES IN ANNOTATIONS
        #MAKE SYNAPTIC PARTNERS CLICKY? like this: <http://www.zapier.com|Text to make into a link>

        if 'update' in self.command or self.global_update is True:
            logger.debug('Pushing updates')
            if self.global_update is True:
                users_to_notify = [ u for u in data['users'] if data['users'][u]['daily_updates'] is True ]
                logger.debug('Global update! ' + str(users_to_notify))
                neurons_to_process = []
                for u in data['users']:
                    neurons_to_process += [ str(n) for n in data['users'][u]['neurons'] ]
            else:
                ts = self.slack_client.api_call("chat.postMessage", channel='@' + self.user,
                                    text='Got it! Collecting intel - please wait...', as_user=True)['ts']
                users_to_notify = [ self.user ]
                neurons_to_process = [ str(s) for s in data['users'][self.user]['subscriptions'] ]

            #Gather new data here - this costs time!
            new_data,skdata = self.process_neurons ( neurons_to_process )

            for u in users_to_notify:
                not_changed = []
                response = ''
                if not skids:
                    neurons_to_update = [ str(s) for s in data['users'][u]['subscriptions'] ]
                else:
                    neurons_to_update = [ str(s) for s in skids ]

                for n in neurons_to_update:
                    n = str(n)

                    #Changes are sorted into basic values and more complicated stuff (i.e. synaptic partners)
                    changes = {
                                'basic': {},
                                'synaptic_partners': {},
                                'new_annotations': [],
                                'annotations': {    'new': [],
                                                    'gone': []
                                                    }
                                }

                    #Search for change in basic values
                    for e in basic_values:
                        #If value is new, skip it for now and just write it back
                        if e not in data['users'][u]['neurons'][n]:
                            continue

                        if new_data[n][e] != data['users'][u]['neurons'][n][e]:
                            changes['basic'][e] = [ new_data[n][e] , data['users'][u]['neurons'][n][e] ]

                    #Search for changes in values that are lists (i.e. up- and downstream partners)
                    for e in new_data[n]['synaptic_partners']:
                        try:
                            if new_data[n]['synaptic_partners'][e] != data['users'][u]['neurons'][n]['synaptic_partners'][e]:
                                changes['synaptic_partners'][e] = [ new_data[n]['synaptic_partners'][e], data['users'][u]['neurons'][n]['synaptic_partners'][e] ]
                        except:
                            #When partner is entirely new
                            changes['synaptic_partners'][e] = [ new_data[n]['synaptic_partners'][e], {'incoming':'-', 'outgoing': '- '} ]

                    #Search for partners that have vanished
                    for e in data['users'][u]['neurons'][n]['synaptic_partners']:
                        try:
                            if new_data[n]['synaptic_partners'][e] != data['users'][u]['neurons'][n]['synaptic_partners'][e]:
                                changes['synaptic_partners'][e] = [ new_data[n]['synaptic_partners'][e], data['users'][u]['neurons'][n]['synaptic_partners'][e] ]
                        except:
                            changes['synaptic_partners'][e] = [ {'incoming':'-', 'outgoing': '- '} , data['users'][u]['neurons'][n]['synaptic_partners'][e] ]

                    try:
                        #Find new annotations
                        for e in new_data[n]['annotations']:
                            if e not in data['users'][u]['neurons'][n]['annotations']:
                                changes['annotations']['new'].append(e)

                        #Find annotations that have vanished:
                        for e in data['users'][u]['neurons'][n]['annotations']:
                            if e not in new_data[n]['annotations']:
                                changes['annotations']['gone'].append(e)
                    except:
                        #E.g. if annotations have not yet been tracked in the old dataset
                        pass

                    #If changes have been found, generate response
                    if changes['basic'] or changes['synaptic_partners'] or changes['annotations']['new'] or changes['annotations']['gone']:
                        nodes = skdata.set_index('skeleton_id').ix[ str(n) ].nodes
                        root_index = nodes [ nodes.type == 'root' ].index[0]
                        root = nodes.ix[ root_index  ]

                        #root = [nd for nd in skdata[ neurons_to_process.index(n) ][0] if nd[1] == None][0]

                        url = url_to_coordinates((root.x, root.y, root.z),
                                                 stack_id=5,
                                                 tool='tracingtool',
                                                 active_skeleton_id=n,
                                                 remote_instance=remote_instance,
                                                 active_node_id=root[0])
                        link = '<' + url + '|' + new_data[n]['name'] + '>'
                        response += '%s - #%s (changes since %s) \n```' % ( link , str(n), data['users'][u]['neurons'][n]['last_update'] )
                    else:
                        not_changed.append(n)

                    #Basic values first
                    if changes['basic']:
                        if True in [ e in changes['basic'] for e in basic_values ]:
                            table = [ [ 'Value', 'New', 'Old' ] ] + [ [ e, changes['basic'][e][0], changes['basic'][e][1] ] for e in basic_values if e in changes['basic'] ]
                            response += tabulate(table) + '\n'
                    if changes['annotations']['new']:
                        response += 'New annotations: %s \n' % '; '.join(changes['annotations']['new'])
                    if changes['annotations']['gone']:
                        response += 'Deleted annotations: %s \n' % '; '.join(changes['annotations']['gone'])
                    #Now connectivity
                    if changes['synaptic_partners']:
                        partner_names = get_names(list(changes['synaptic_partners'].keys()),
                                                  remote_instance=remote_instance)

                        #If partner does not exist anymore:
                        partner_names.update( { e:'not found' for e in list( changes['synaptic_partners'].keys() ) if e not in partner_names } )

                        response += 'Synaptic partners:\n'

                        table = [ [ 'Name', 'SKID', 'Synapses from (new/old)', 'Synapses to (new/old)' ] ]
                        table += [ [ partner_names[e], e, str(changes['synaptic_partners'][e][0]['incoming'])+'/'+str(changes['synaptic_partners'][e][1]['incoming']), str(changes['synaptic_partners'][e][0]['outgoing'])+'/'+str(changes['synaptic_partners'][e][1]['outgoing']),   ] for e in changes['synaptic_partners'] ]
                        response += tabulate(table) + '\n'

                    if changes['basic'] or changes['synaptic_partners'] or changes['annotations']['new'] or changes['annotations']['gone']:
                        response += '```\n'

                if response:
                    self.slack_client.api_call("chat.postMessage", channel='@' + u,
                                      text= response  , as_user=True)
                    if not_changed:
                        self.slack_client.api_call("chat.postMessage", channel='@' + u,
                                      text= 'No changes for neurons `' + ', '.join(not_changed) + '`', as_user=True)
                    #Reset response
                    response = ''
                else:
                    logger.debug( 'No changes for user ' + u )
                    self.slack_client.api_call("chat.postMessage", channel= '@' + u,
                                      text='None of the neurons you are subscribed to have changed recently!', as_user=True)

            #Write back changes to DB
            users = data['users']
            users[u]['neurons'].update(new_data)
            data['users'] = users
        try:
            data.close()
            logger.debug('Database update successful')
            if self.user != None:
                self.slack_client.api_call("chat.postMessage", channel='@' + self.user,
                                          text=response, as_user=True)
            else:
                logger.debug('User is None: ' + response)
        except:
            logger.error('Failed to update database')
            if self.user != None:
                self.slack_client.api_call("chat.postMessage", channel='@' + self.user,
                                          text='Oops! Something went wrong. If you made any changes to your subscriptions, please try again.', as_user=True)
            else:
                logger.debug('User is None: ' + response)
        return


class return_review_status(threading.Thread):
    """ Class to process incoming review-status request
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def run(self):
        """ Extracts skids from command and returns these neurons review-status.
        """
        logger.debug('Started new thread %i for command <%s>' % (self.id, self.command ) )
        skids = parse_neurons(self.raw_command)

        ts = self.slack_client.api_call("chat.postMessage",
                                        channel=self.channel,
                                        text='Got it! Collecting intel - '
                                             'please wait...',
                                        as_user=True)['ts']

        for s in skids:
            if not neuron_exists(s, remote_instance=remote_instance):
                response = "I'm sorry - the neuron #%s does not seem to " \
                           "exists. Please try again." % s
                self.slack_client.api_call("chat.postMessage",
                                           channel=self.channel,
                                           text=response,
                                           as_user=True)
                return

        if not skids:
            response = 'Please provide neurons as *#skid*, *annotation=" "* ' \
                       'or *name=" "*! For example: _@catbot review-status ' \
                       '#957684_'
        else:
            r_status = get_review(skids, remote_instance=remote_instance)
            response = "This is the current review status:\n ```{}``` ".format(r_status.to_string())

        self.slack_client.api_call("chat.delete",
                                   channel = self.channel,
                                   ts = ts)

        if response:
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       text=response, as_user=True)

        return


class return_plot_neuron(threading.Thread):
    """ Class to process incoming plot neuron request
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def run(self):
        """ Extracts skids from command and generates + uploads a file
        """
        logger.debug('Started new thread %i for command <%s>' % (self.id,
                                                                 self.command))
        skids = parse_neurons(self.raw_command)

        if not skids:
            response = 'Please provide neurons as *#skid*, *annotation=" "* ' \
                       'or *name=" "*! For example: _@catbot plot-neuron ' \
                       '#957684_'
        else:
            for s in skids:
                if not neuron_exists(s, remote_instance=remote_instance):
                    response = "I'm sorry - the neuron #%s does not seem to " \
                               "exists. Please try again." % s
                    self.slack_client.api_call("chat.postMessage",
                                               channel=self.channel,
                                               text=response, as_user=True)
                    return

            ts = self.slack_client.api_call("chat.postMessage",
                                            channel=self.channel,
                                            text='Got it! Generating plot - '
                                                 'please wait...',
                                            as_user=True)['ts']

            # Get all volumes
            vlist = pymaid.get_volume(remote_instance=remote_instance)
            vlist = vlist.name.values

            # Find the volumes we are supposed to plot
            v2plot = ['v14.neuropil'] + [v for v in vlist if v in self.command]

            vols = pymaid.get_volume(v2plot, remote_instance=remote_instance)

            if not isinstance(vols, dict):
                vols = {vols.name : vols}

            vols['v14.neuropil'].color = (250, 250, 250, .3)

            # Find out if colors for volumes are specified:
            for v in vols:
                if re.search('{v}=((.*))', self.command):
                    vols[v].color = re.search('{v}=((.*))', self.command).group(1)

            try:
                fig, ax = plot2d(skids + list(vols.values()),
                                 method='3d_complex',
                                 remote_instance=remote_instance)
            except Exception as e:
                self.slack_client.api_call("chat.delete",
                                           channel = self.channel,
                                           ts = ts
                                           )
                logger.error('Error in plotneuron()', exc_info = True)
                self.slack_client.api_call("chat.postMessage",
                                           channel=self.channel,
                                           text='Oops - something went wrong '
                                                'while trying to plot your '
                                                'neuron(s).',
                                           as_user=True)
                return

            #Add legend if more than one neuron
            if len(skids) > 1:
                plt.legend()

            #Check if output directory exists
            if not os.path.isdir( 'renderings' ):
                os.makedirs( 'renderings' )

            #Save the figure
            plt.savefig('renderings/neuron_plot.png',
                        transparent=False, dpi=300)

            #Delete stand-by message
            self.slack_client.api_call("chat.delete",
                                       channel=self.channel,
                                       ts=ts)

            #Upload neuron plot
            with open('renderings/neuron_plot.png', 'rb') as f:
                self.slack_client.api_call("files.upload",
                                           channels=self.channel,
                                          file = f,
                                          title = 'Neuron plot',
                                          initial_comment = 'Neurons #%s' % ' #'.join([str(s) for s in skids])
                                          )
            response = ''

        if response:
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       text=response, as_user=True)
        return


class return_connectivity(threading.Thread):
    """ Class to process incoming connectivity requests
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info = True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def run(self):
        """ Returns urls for a list of neurons
        """
        skids = parse_neurons( self.raw_command )

        logger.debug('Started new thread %i for command <%s>' % (self.id,
                                                                 self.command))

        for s in skids:
            if not neuron_exists(s, remote_instance=remote_instance):
                response = "I'm sorry - the neuron #%s does not seem to " \
                           "exists. Please try again." % s
                self.slack_client.api_call("chat.postMessage",
                                           channel=self.channel,
                                           text=response, as_user=True)
                return

        self.command = self.command.replace('”','"')

        try:
            thresh = int(re.search('threshold=(\d+)',self.command).group(1))
        except:
            thresh = 1

        try:
            filt = re.search('filter="(.*?)"',self.command).group(1).split(',')
            logger.debug('Filtering partners for: ' + str(filt) )
        except:
            filt = []

        directions = []
        if 'incoming' in self.command or 'upstream' in self.command:
            directions.append('upstream')
        if 'outgoing' in self.command or 'downstream' in self.command:
            directions.append('downstream')

        if not directions:
            directions = ['upstream', 'downstream']

        if not skids:
            response = 'Please provide neurons as `#skid`, `annotation=" "` ' \
                       'or `name=" "`! For example: `@catbot partners #957684`'
        else:
            cn = get_partners(skids,
                              remote_instance=remote_instance,
                              threshold=thresh)

            attachments = []

            rel_colors = {'upstream': '#2874A6',
                          'downstream': '#C0392B',
                          'gapjunction': '#16A085',
                          'attachment': '#F1C40F'}

            for d in directions:
                this_cn = cn[cn.relation==d].drop(['relation', 'total', 'num_nodes'], axis=1)
                this_at = dict(title='{} partners'.format(d),
                               text='```{}```'.format(this_cn.iloc[0:70].reset_index(drop=True).to_string()),
                               mrkdwn='true',
                               color=rel_colors[d],
                               footer='Truncated (too many neurons)!!!' if this_cn.shape[0] > 70 else '')
                attachments.append(this_at)
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       text='Here are the partners of neurons'
                                            ' you requested:',
                                       attachments=attachments,
                                       as_user=True)

        return ''



class return_url(threading.Thread):
    """ Class to process incoming url to neuron request
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def run(self):
        """ Returns urls for a list of neurons
        """
        skids = parse_neurons(self.raw_command)
        logger.debug('Started new thread %i for command <%s>' % (self.id,
                                                                 self.command))

        for s in skids:
            if not neuron_exists(s, remote_instance=remote_instance):
                response = "I'm sorry - the neuron #%s does not seem to " \
                           "exists. Please try again." % s
                self.slack_client.api_call("chat.postMessage",
                                           channel=self.channel,
                                           text=response,
                                           as_user=True)
                return

        if not skids:
            response = 'Please provide neurons as `#skid`, `annotation=" "` ' \
                       'or `name=" "`! For example: `@catbot plot-neuron #957684`'
        else:
            response = 'Here are URLs to the neurons you have provided!'
            skdata = get_neuron(skids, remote_instance=remote_instance,
                                connector_flag=0, tag_flag=0,
                                get_history=False)

            skdata = pymaid.CatmaidNeuronList(skdata)

            for neuron in skdata:
                root = neuron.nodes[neuron.nodes.type=='root']
                url = url_to_coordinates(root,
                                         stack_id=5,
                                         tool='tracingtool',
                                         active_skeleton_id=neuron.skeleton_id,
                                         active_node_id=root.treenode_id.values,
                                         remote_instance=remote_instance)
                for u in url:
                    response += '\n *#%s*: %s' % (neuron.skeleton_id, u)

        if response:
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       text=response, as_user=True)

        return response


class return_zotero(threading.Thread):
    """ Class to process requests to access Zotero
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def run(self):
        """ Lists all available commands and their syntax.
        """
        logger.debug('Started new thread %i for command <%s>' % (self.id,
                                                                 self.command))

        #First extract tags to search for
        command = self.command.replace('zotero', '')
        tags = command.split(' ')

        if '' in tags:
            tags.remove('')

        ts = self.slack_client.api_call("chat.postMessage",
                                        channel=self.channel,
                                        text='Searching Zotero database. '
                                             'Please hold...',
                                        as_user=True)['ts']

        #Retrieve all items in library
        items = zot.everything ( zot.items() )
        pdf_files = [ i for i in items if i['data']['itemType'] == 'attachment' and i['data']['title'] == 'Full Text PDF' ]
        logger.debug('Searching %i Zotero items for:' % len(items))
        logger.debug(tags)

        self.slack_client.api_call("chat.delete",
                                   channel=self.channel,
                                   ts=ts)

        if 'file' in tags:
            dl_file = True
            tags.remove('file')
            if len(tags) > 1:
                self.slack_client.api_call("chat.postMessage",
                                           channel=self.channel,
                                           text='If you want me to grab you a '
                                                'PDF, please give me a single '
                                                'zotero key: `@catbot zotero '
                                                'file <ZOTERO-ID>`',
                                           as_user=True)
            elif len(tags) == 1:
                this_item = [f for f in pdf_files if f['data']['parentItem'].lower() == tags[0]]

                if this_item:
                    filename = this_item[0]['data']['filename']
                    zot.dump( this_item[0]['key'] , filename )
                    with open( filename , 'rb') as f:
                        self.slack_client.api_call("files.upload",
                                                   channels=self.channel,
                                                   file = f,
                                                   title = filename,
                                                   initial_comment = '')
                    return
                else:
                    self.slack_client.api_call("chat.postMessage",
                                               channel=self.channel,
                                               text="Oops! I can't seem to "
                                                    "find a PDF to the Zotero "
                                                    "key you have given me...",
                                               as_user=True)
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
                        logger.debug('Found tag %s in %s' % ( t, e['data']['date'] ) )
                    elif t.lower() in [ a['lastName'].lower() for a in e['data']['creators']]:
                        this_tag = True
                        logger.debug('Found tag %s in %s' % ( t, str([ a['lastName'].lower() for a in e['data']['creators']]) ) )
                    elif t.lower() in e['data']['title'].lower():
                        this_tag = True
                        logger.debug('Found tag %s in %s' % ( t, e['data']['title'].lower() ) )
                    elif True in [ t.lower() in a['tag'].lower() for a in e['data']['tags'] ]:
                        this_tag = True
                        logger.debug('Found tag %s in %s (%s)' % ( t, [ a['tag'].lower() for a in e['data']['tags'] ], [ t.lower() in a['tag'].lower() for a in e['data']['tags'] ] ) )
                except:
                    pass

                include.append( this_tag )

            if False not in include:
                logger.debug( str(tags) + str(include) + e['data']['date'] )
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
            response += 'Use `@catbot zotero file <ZOTERO-ID>` if you want ' \
                        'me to grab you the PDF!'
        else:
            response = 'Sorry, I could not find anything matching your ' \
                       'criteria!'

        self.slack_client.api_call("chat.postMessage",
                                   channel=self.channel,
                                   text=response, as_user=True)

        return


class return_help(threading.Thread):
    """ Class to process incoming help request
    """
    def __init__(self, slack_client ,command,channel):
        try:
            self.command = command.lower()
            self.raw_command = command
            self.channel = channel
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info = True)
        return None

    def run(self):
        """ Lists all available commands and their syntax.
        """
        logger.debug('Started new thread %i for command <%s>' % (self.id, self.command))
        if 'partners' in self.command:
            response = '`partners` returns the synaptic partners for a list of <neurons>. You can pass me keywords to filter the list: \n'
            response += '1. Add `incoming` or `outgoing` to limit results to up- or downstream partners \n'
            response += '2. Add `filter="tag1,tag2"` to filter results for neuron names (case-insensitive, non-intersecting)\n'
            response += '3. Add `threshold=3` to filter partners for a minimum number of synapses\n'
        elif 'nblast-fafb' in self.command:
            response = '`nblast-fafb` blasts the provided neuron against the nightly dump of FAFB neurons. Use combinations of the following optional arguments to refine: \n'
            response += '1. Use `nblast-fafb <neuron> mirror` to mirror neuron before nblasting (if you are looking for the left version of your neuron). \n'
            response += '2. Use `nblast-fafb <neuron> hits=N` to return the top N hits in the 3D plot. Default is 3\n'
            response += '4. Use `nblast-fafb <neuron> cores=N` to set the number of CPU cores used to nblast. Default is 8\n'
            response += '5. Use `nblast-fafb <neuron> prefermu` to sort hits by reverse score (muscore) rather than forward score\n'
            response += '6. Use `nblast-fafb <neuron> usealpha` to make nblast value backbones higher than smaller neurites\n'
        elif 'nblast' in self.command:
            response = '`nblast` blasts the provided neuron against the flycircuit database. Use combinations of the following optional arguments to refine: \n'
            response += '1. Use `nblast <neuron> nomirror` to prevent mirroring of neurons before nblasting (i.e. if cellbody is already on the flys left). \n'
            response += '2. Use `nblast <neuron> hits=N` to return the top N hits in the 3D plot. Default is 3\n'
            response += '3. Use `nblast <neuron> gmrdb` to nblast against Janelia GMR lines  \n'
            response += '4. Use `nblast <neuron> cores=N` to set the number of CPU cores used to nblast. Default is 8\n'
            response += '5. Use `nblast <neuron> prefermu` to sort hits by reverse score (muscore) rather than forward score\n'
            response += '6. Use `nblast <neuron> usealpha` to make nblast value backbones higher than smaller neurites\n'
        elif 'neurondb' in self.command:
            response = '`neurondb` lets you access and edit the neuron database. \n'
            response += 'I am using skeleton IDs as unique identifiers -> you can search for names/annotations/etc but I need a SKID when you want to add/edit an entry! \n'
            response += '1. Use `neurondb list` to get a list of all neurons in the database. \n'
            response += '2. Use `neurondb search <tag1> <tag2> ...` to search for hits in the database. \n'
            response += '3. Use `neurondb show <single neuron>` to show a summary for those skeleton ids. \n'
            response += '4. Use `neurondb edit <single neuron> name="MVP2" comments="awesome neuron"` to edit entries. \n'
            response += '   For list entries such as <comments> or <neuropils> you can use "comments=comment1;comment2;comment3" to add multiple entries at a time. \n'
            response += '5. To delete specific comments/tags use e.g. `neurondb *delete* comments=<index>` to remove the <index> (e.g. 1 = first) comment. \n'
        elif 'subscription' in self.command:
            response = '`subscription` lets you flag neurons of interest and I will keep you informed when they are modified. \n'
            response += 'By default you will automatically receive daily updates (in the morning) \n'
            response += 'but you can use `update` at any time to get an unscheduled summary.'
            response += '1. Use `subscription list` to get a list of all neurons you are currently subscribed to. \n'
            response += '2. Use `subscription new <neuron(s)>` to subscribe to neurons. \n'
            response += '3. Use `subscription update` to get an unscheduled summary of changes. Unless you also provide <neurons>, you will get all subscriptions. \n'
            response += '4. Use `subscription delete <neuron(s)>` to unsubscribe to neurons. \n'
        elif 'plot' in self.command:
            response = '`plot` lets you plot neurons of interest.  \n'
            response += '1. Use `plot <neuron(s)> neuropil1 neuropil2` to make me plot neuropils. \n'
            response += '2. Use `plot <neuron(s)> neuropil1=(r,g,b) neuropil2=(r,g,b)` to give neuropils specific colors (`r`,`g`,`b` must be range 0-1). \n'
            response += 'Currently, I can offer these neuropils: `MB`, `SIP` ,`AL`, `CRE`, `SLP`, `LH` \n'
        else:
            functions = [
                        '`neurondb` : accesses the neuron database. Use `@catbot help neurondb` to learn more.',
                        '`subscribe` : accesses the subscription system. Use `@catbot help subscription` to learn more.',
                        '`review-status <neurons>` : give me a list of neurons and I will tell you their review status.',
                        '`plot <neurons>` : give me a list of neurons to plot. Use `@catbot help plot` to learn about how to show neuropils.',
                        '`url <neurons>` : give me a list of neurons and I will generate urls to their root nodes.',
                        '`nblast <neuron>` : give me a *single* neuron and let me run an nblast search. Use `@catbot help nblast` to learn more.',
                        '`nblast-fafb <neuron>` : `nblast` against a nightly dump of (simplified) CATMAID neurons. Use `@catbot help nblast-fafb` to learn more.',
                        '`zotero TAG1 TAG2 TAG3` : give me tags and I will search our Zotero group for you',
                        '`zotero file ZOTERO-ID` : give me a Zotero ID and I will download the PDF for you',
                        '`partners <neurons>` : returns synaptic partners. Use `@catbot help partners` to learn more.',
                        '`help` : You have just used that, dummy...'
                        ]

            response = 'Currently I can help you with the following commands:'
            for f in functions:
                response += '\n' + f
            response += '\n You can pass me `<neurons>` either via their skids `#451234`, annotation `annotation="DA1"` or name `name="DA1 PN"`'

        if response:
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       text=response, as_user=True)
        return


class neurondb_manager(threading.Thread):
    """ Class to process incoming request to the neuron database
    """
    def __init__(self, slack_client, command, channel, user):
        try:
            self.command = command
            self.raw_command = command
            self.channel = channel
            self.user = user
            self.slack_client = slack_client
            self.id = random.randint(1,99999)
            threading.Thread.__init__(self)
        except Exception as e:
            logger.error('Failed to initiate thread for ' + self.command,
                         exc_info=True)

    def join(self):
        try:
            threading.Thread.join(self)
            logger.debug('Thread %i closed' % self.id )
            return None
        except Exception as e:
            logger.error('Failed to join thread for ' + self.url,
                         exc_info=True)
        return None

    def delete_value(self, neuron ):
        """ Generates a new entry for a given skid
        """
        for e in self.entries:
            try:
                index_to_delete = int ( re.search( e + '=(\d+)', self.command ).group(1) ) - 1
                neuron[e].pop( index_to_delete )
            except:
                pass

        neuron['last_edited'] = str(date.today())

        return neuron

    def edit_entry(self, neuron ):
        """ Generates a new entry for a given skid
        """
        for e in self.entries:
            try:
                new_value = re.search( e + '="(.*?)"', self.command ).group(1)

                if type( neuron[e] ) == type( list() ):
                    neuron[e] += [v + ' (' + self.user + ')' for v in new_value.split(';')]
                else:
                    neuron[e] = new_value
            except:
                pass

        neuron['last_edited'] = str(date.today())

        return neuron


    def plot_results(self, neuron):
        """ Returns summary of neuron as string ready for posting
        """

        table = []
        for k in self.entries:
            if type(neuron[k]) != type ( list() ):
                table.append ( [ k.capitalize(), str( neuron[k] ) ] )
            elif k == 'comments':
                for i , e in enumerate( neuron[k] ):
                    if i == 0:
                        table.append ( [ k.capitalize(), e ] )
                    else:
                        table.append ( [ '' , e ] )
            else:
                table.append ( [ k.capitalize(), "; ".join( neuron[k] ) ] )

        return '```' + tabulate(table) + '```\n'

    def run(self):
        """ Opens neuron database, returns/edits entries.
        """

        #Define entries here!
        self.entries = ['name', 'catmaid_name', 'skid', 'alternative_names',
                        'type', 'neuropils', 'status', 'tags', 'last_edited',
                        'comments']

        skids = parse_neurons( self.raw_command )

        if skids:
            self.neuron_names = get_names( skids, remote_instance )

        try:
            data = shelve.open('neurondb')
        except:
            self.slack_client.api_call("chat.postMessage",
                                       channel=self.channel,
                                       ext='Unable to open neuron database!',
                                       as_user=True)
            return

        if 'list' in self.command.lower():
            response = 'I have these neurons in my database:\n'
            response += '```' + tabulate( [ ['*Name*','*Skid*' ] ] + [ [ data[k]['name'], k ] for k in data.keys() ] ) + '```'

        elif 'show' in self.command.lower():
            if not skids:
                response = 'Sorry, I need at least a single #skid.'
            else:
                response = ''
                for s in skids:
                    if s in data:
                        response += self.plot_results( data[s] )
                    else:
                        response += 'Sorry, I did not find skid #%s in my ' \
                                    'database!' % s

        elif 'search' in self.command.lower():
            #First extract tags to search for
            search = self.command.lower().replace('neurondb', '')
            tags = search.split(' ')
            if '' in tags:
                tags.remove('')

            hits = set()
            for n in data.keys():
                for t in tags:
                    if [ t in data[n][entry].lower() for entry in data[n] if type( data[n][entry] ) != type ( list() ) ]:
                        hits.add(n)
                        break
                    else:
                        for entry in [ e for e in data[n] if type( data[n][entry] != type ( list() ) ) ]:
                            if [ t in data[n][entry][e].lower() for e in data[n][entry] ]:
                                hits.add(n)
                                break

            if hits:
                response = 'I found the following match(es):\n'
                response += '```' + tabulate([['*Name*', '*Skid*']] + [[ data[n]['name'], n] for n in hits ] ) +'```'
            else:
                response = 'Sorry, could not find anything matching your query!'

        elif 'edit' in self.command.lower():
            if len(skids) != 1:
                response = 'Please give me a *single* skid: e.g. `@catbot ' \
                           'neurondb new #435678`'
            else:
                if skids[0] not in data:
                    if skids[0] in self.neuron_names:
                        self.slack_client.api_call("chat.postMessage",
                                                   channel=self.channel,
                                                   text='Neuron #%s not in my '
                                                        'database - created a '
                                                        'new entry!' % (skids[0]),
                                                   as_user=True)

                        data[skids[0]] = {'name': '',
                                          'catmaid_name': self.neuron_names[skids[0]],
                                          'skid': skids[0],
                                          'alternative_names': [],
                                          'type': '',
                                          'neuropils': [],
                                          'status': 'unknown',
                                          'tags': '',
                                          'last_edited': str(date.today()),
                                          'comments': []
                                            }
                    else:
                        self.slack_client.api_call("chat.postMessage",
                                                   channel=self.channel,
                                                   text='Could not find neuron'
                                                        ' #%s in my database '
                                                        'or in CATMAID!' % (skids[0]),
                                                   as_user=True)

                data[ skids[0] ] = self.edit_entry( data[ skids[0] ] )
                response = 'Updated entry for neuron %s #%s!' % ( data[ skids[0] ]['name'], skids[0] )
        elif 'delete' in self.command.lower():
            if len(skids) != 1:
                response = 'Please give me a *single* skid: e.g. `@catbot ' \
                           'neurondb delete #435678`'
            elif skids[0] not in data:
                response = 'Could not find neuron #%s in my database.' % (skids[0])
            else:
                data[ skids[0] ] = self.delete_value( data[ skids[0] ] )
                response = 'Updated entry for neuron %s #%s!' % (data[skids[0]]['name'],
                                                                 skids[0])

        else:
            response = 'Not quite sure what you want me to do with the ' \
                       'neurondb. Please use `@catbot help neurondb` to ' \
                       'learn more.'

        try:
            data.close()
            self.slack_client.api_call("chat.postMessage", channel=self.channel,
                                      text=response, as_user=True)
        except:
            self.slack_client.api_call("chat.postMessage", channel=self.channel,
                                      text='Oops! Something went wrong. If '
                                           'you made any changes to the '
                                           'database please try again.',
                                      as_user=True)

        return


def time2hh():
    """ Returns time to HH.
    """

    # First get hours until next Friday
    friday = date.today()
    while friday.weekday() != 4:
        friday += timedelta(days=1)

    # Now get time until next Friday 5:30pm
    next_hh = datetime(friday.year, friday.month, friday.day, 17, 30)

    # If it is past 5:30 on a Friday, it's HH
    if next_hh <= datetime.now():
        return "It's Happy Hour time! Go have a drink :beer:"

    time2hh = next_hh - datetime.now()
    if time2hh.days > 0:
        return "It's {} days, {} hours and {} minutes " \
               "to Happy Hour :(".format(time2hh.days,
                                         time2hh.seconds // 3600,
                                         (time2hh.seconds // 60) % 60)
    elif time2hh.seconds // 3600 > 0:
        return "It's {} hours and {} minutes to " \
               "Happy Hour!".format(time2hh.seconds // 3600,
                                    (time2hh.seconds // 60) % 60)
    elif time2hh.seconds > 60:
        return "It's only another {} minutes to " \
               "Happy Hour :)".format((time2hh.seconds // 60) % 60)
    else:
        return "Oh boy, we're almost there! Give me a {} second " \
               "countdown!".format(time2hh.seconds)


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
                user = user_list[output['user']]
                logger.debug('Message from %s (%s): %s' % (user,
                                                           output['user'],
                                                           output['text']))
                return output['text'].split(botconfig.AT_BOT)[1].strip(), \
                       output['channel'], \
                       user
    return None, None, None


def parse_neurons(command):
    """Parses the command in search of skeleton IDs, neuron names and annotations
    """

    skids = []

    #First find skids:
    if re.findall('#(\d+)', command):
        skids += re.findall('#(\d+)', command)

    if 'name="' in command:
        skids += get_skids_by_name(re.search('name="(.*?)"', command).group(1),
                                   allow_partial=True,
                                   remote_instance=remote_instance,
                                   project_id=botconfig.PROJECT_ID)

    if 'annotation="' in command:
        skids += get_skids_by_annotation(re.search('annotation="(.*?)"',
                                                   command).group(1),
                                         remote_instance=remote_instance,
                                         project_id=botconfig.PROJECT_ID)

    return list(set([int(n) for n in skids]))


class user_list:
    """ Works like a dictionary mapping user ID to user name. Will update
    itself when ID for user is unknown (i.e. a new user was added on Slack).

    Will return 'unknown user' if no user for given ID is found.
    """

    def __init__(self, slack_client):
        self.slack_client = slack_client
        self.update_users()

    def update_users(self):
        self.ul = self.slack_client.api_call('users.list')['members']
        self.dict = {e['id']: e['name'] for e in self.ul}

    def __getitem__(self, key):
        # Update user list if necessary
        if key not in self.dict:
            self.update_users()

        if key in self.dict:
            return self.dict[key]

        return 'unknown user'

    def __getattr__(self, attr):
        return getattr(self.dict, attr)


if __name__ == '__main__':
    import sys

    #Create logger
    logger = logging.getLogger('pybotLog')
    #Create file handler which logs even debug messages
    fh = logging.FileHandler('pybot.log')
    fh.setLevel(logging.DEBUG)
    #Create console handler - define different log level is desired
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    #Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(name)s - '
                                  '%(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    #Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    if 'debug' in sys.argv:
        logger.setLevel(logging.DEBUG)
        logger.info('Starting Pybot in Debug Mode...')
    else:
        logger.setLevel(logging.INFO)
        logger.info('Starting Pybot...')

    #botconfig.py holds credentials for CATMAID, Slack and Zotero
    try:
        import botconfig
    except:
        logger.error('Import of botconfig.py failed. Please make sure you'
                     ' have this configuration file correctly set up!')
        sys.exit()

    #Initialize CATMAID instance (without caching)
    remote_instance = CatmaidInstance(botconfig.SERVER_URL,
                                      botconfig.HTTP_USER,
                                      botconfig.HTTP_PW,
                                      botconfig.AUTHTOKEN,
                                      project_id=botconfig.PROJECT_ID,
                                      caching=False)

    # Set loggers and progress bars
    pymaid.set_pbars(hide=True)
    pymaid.set_loggers('ERROR')

    #Inintialize slack client
    slack_client = SlackClient(botconfig.SLACK_KEY)

    if botconfig.ZOT_KEY:
        # Zotero( group_id, library_type, API_key )
        zot = zotero.Zotero(botconfig.ZOT_GRP_ID, 'group', botconfig.ZOT_KEY)
    else:
        zot = None

    open_threads = []
    open_processes = []
    previous_open_threads = 0
    command = channel = None
    last_global_update = date.today()

    user_list = user_list(slack_client)
    logger.debug('Users: ' + ', '.join(list(user_list.values())))

    if slack_client.rtm_connect():
        logger.info("Pybot connected and running!")
        while True:
            try:
                command, channel, user = parse_slack_output(slack_client.rtm_read(),
                                                            user_list)
            except WebSocketConnectionClosedException as e:
                logger.error('Caught websocket disconnect, reconnecting...',
                             exc_info = True)
                time.sleep(botconfig.READ_WEBSOCKET_DELAY)

                if slack_client.rtm_connect():
                    logger.error('Reconnect successful!')
                else:
                    logger.error('Reconnect failed!')

            except Exception as e:
                logger.error('Error parsing slack output: ' + e, exc_info=True)

            #On midnight, trigger global update
            if date.today() != last_global_update:
                last_global_update = date.today()
                t = subscription_manager(slack_client, '', None, None,
                                         global_update = True )
                t.start()
                open_threads.append( t )

            if command and channel and user != botconfig.BOT_NAME:
                #Replace odd ” with "
                command = command.replace( '”' , '"' )

                logger.info('Commmand by %s in channel %s: %s' % (user,
                                                                  channel,
                                                                  command))

                #Only process if not at max open threads
                if len(open_threads)+len(open_processes) <= botconfig.MAX_PARALLEL_REQUESTS:
                        t = None
                        if 'help' in command.lower():
                            t = return_help(slack_client, command, channel)
                        elif 'review-status' in command.lower():
                            t = return_review_status(slack_client, command,
                                                     channel)
                        elif 'plot' in command.lower():
                            try:
                                t = return_plot_neuron(slack_client, command,
                                                       channel)
                            except Exception as e:
                                logger.error("Error while plotting: " + e,
                                             exc_info=True )
                                slack_client.api_call("chat.postMessage",
                                                      channel=channel,
                                                      text='Ooops, something '
                                                           'went wrong... '
                                                           'please try again '
                                                           'or contact an '
                                                           'admin.',
                                                      as_user=True)
                        elif 'url' in command.lower():
                            t = return_url(slack_client, command, channel)
                        elif 'partners' in command.lower():
                            t = return_connectivity(slack_client, command,
                                                    channel)
                        elif 'neurondb' in command.lower():
                            try:
                                t = neurondb_manager(slack_client, command,
                                                     channel, user)
                            except Exception as e:
                                logger.error("Error while database "
                                             "operation: " + e, exc_info=True)
                                slack_client.api_call("chat.postMessage",
                                                      channel=channel,
                                                      text='Ooops, something '
                                                           'went wrong... '
                                                           'please try again '
                                                           'or contact an '
                                                           'admin.',
                                                      as_user=True)
                        elif 'subscription' in command.lower():
                            try:
                                t = subscription_manager(slack_client, command,
                                                         channel, user)
                            except Exception as e:
                                logger.error("Error while processing "
                                             "subscription: " + e,
                                             exc_info=True )
                                slack_client.api_call("chat.postMessage",
                                                      channel=channel,
                                                      text='Ooops, something '
                                                           'went wrong... '
                                                           'please try again '
                                                           'or contact an '
                                                           'admin.',
                                                      as_user=True)
                        elif 'nblast' in command.lower():
                            # For some odd reason, threading does not prevent
                            # freezing while waiting R code to return nblast
                            # results.
                            # Therfore nblasting is used as a fire and forget
                            # script by creating a new subprocess

                            skids = parse_neurons( command )

                            if len(skids) == 1:
                                if not neuron_exists(skids[0],
                                                     remote_instance=remote_instance):
                                        response = "I'm sorry - the neuron " \
                                                   "#%s does not seem to " \
                                                   "exists. Please try " \
                                                   "again." % skids[0]
                                        slack_client.api_call("chat.postMessage",
                                                              channel=channel,
                                                              text=response,
                                                              as_user=True)
                                else:
                                    prefermu = 'prefermu' in command
                                    alpha = 'alpha' in command

                                    try:
                                        hits = int(re.search('hits=(\d+)',
                                                             command).group(1))
                                    except:
                                        hits = 3

                                    try:
                                        cores = int(re.search('cores=(\d+)',
                                                             command).group(1))
                                    except:
                                        cores = 8

                                    if 'gmrdb' in command:
                                        db = 'gmr'
                                    else:
                                        db = 'fc'

                                    if 'fafb' in command.lower():
                                        mirror = 'mirror' in command
                                        p = subprocess.Popen("python3 ffnblast_fafb.py "
                                                             "%s %s %i %i %i "
                                                             "%i %i" % (skids[0],
                                                             channel, int(mirror),
                                                             hits, cores,
                                                             int(prefermu),
                                                             int(alpha)),
                                                             shell=True)
                                    else:
                                        mirror = not 'nomirror' in command
                                        p = subprocess.Popen("python3 ffnblast.py "
                                                             "%s %s %i %i %s %i "
                                                             "%i %i" % (skids[0],
                                                             channel, int(mirror),
                                                             hits, db, cores,
                                                             int(prefermu),
                                                             int(alpha)),
                                                             shell=True)
                                    open_processes.append(p)
                            else:
                                slack_client.api_call("chat.postMessage",
                                                      channel=channel,
                                                      text='I need a *single* '
                                                           'neuron to nblast! '
                                                           'E.g. `@catbot '
                                                           'nblast #123456`',
                                                      as_user=True)
                        elif 'zotero' in command.lower():
                            if zot:
                                try:
                                    t = return_zotero(slack_client, command,
                                                      channel)
                                except Exception as e:
                                    logger.error("Error while processing "
                                                 "Zotero: " + e, exc_info=True)
                            else:
                                response = "Sorry, I can't process your " \
                                           "Zotero request unless you have " \
                                           "it properly configured :("
                                slack_client.api_call("chat.postMessage",
                                                      channel=channel,
                                                      text=response,
                                                      as_user=True)
                        elif 'happy' in command.lower() and 'hour' in command.lower():
                            slack_client.api_call("chat.postMessage",
                                                  channel=channel,
                                                  text=time2hh(),
                                                  as_user=True)
                        else:
                            response = "Not sure what you mean. Type " \
                                       "_@catbot help_ to get a list of " \
                                       "things I can do for you."
                            slack_client.api_call("chat.postMessage",
                                                  channel=channel,
                                                  text=response,
                                                  as_user=True)
                        if t:
                            t.start()
                            open_threads.append( t )

                else:
                    logger.info('Too many open threads - ignoring command '
                                'for now.')
                    slack_client.api_call("chat.postMessage", channel=channel,
                                          text= 'I am currently really busy. '
                                                'Please give me a moment and '
                                                'try again. Cheers!',
                                          as_user=True )

            if len(open_threads) + len(open_processes) != previous_open_threads:
                logger.debug('Open threads/processes: %i' % (len(open_threads) + len(open_processes)))
                previous_open_threads = len(open_threads) + len(open_processes)

            #Try closing open threads
            if open_threads:
                for t in open_threads:
                    if not t.is_alive():
                        t.join()
                        open_threads.remove(t)

            #Check if open processes have finished
            if open_processes:
                for p in open_processes:
                    if p.poll() is not None:
                        open_processes.remove(p)

            time.sleep(botconfig.READ_WEBSOCKET_DELAY)
    else:
        logger.error("Connection failed. Invalid Slack token or bot ID?")



