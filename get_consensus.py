#!/usr/bin/env/python

from stem.descriptor import parse_file, DocumentHandler
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.enterprise import adbapi
from twisted.internet import defer

import txtorcon
import click
import urllib
import json
import datetime
import time

@defer.inlineCallbacks
def write_fingerprints(reactor, dbpool, db_name, consensus_path):
    """
    Downloads the day's first relay-descriptor consensus file from collector and
    parses the contents to the fingerprints table of the database. We save
    the fingerprint, guard/relay/exit flag, continent code, country code, and
    reported bandwidth of each router in the consensus file.

    You want to run get_consensus before building circuits to make sure an actual
    collection of rotersis available.

    Arguments:
        reactor: reactor object for @inlineCallbacks, import in main
        dbpool: object to perform database queries, created in main with
                connection to the MySQL database in use
        db_name: global name of the database, required to perform queries
        consensus_path: relative path to directory of conensus files, includes
                the filename of the consensus created in get_consensus_file()

    Note:
        The location_service_url delivers a json object of the location information
        for an IP address. We blinded it for submission, this should be exchanged to
        any comparable service. Please note that a change might require some changes
        in the expected data structure
    """
    
    location_service_url = '' #BLINDED FOR SUBMISSION
    avg_bandwidths = yield truncate_table(dbpool, db_name)
    get_consensus_file(consensus_path)

    num_lines = sum(1 for line in open(consensus_path))
    with open(consensus_path, 'rb') as consensus_file:
        with click.progressbar(parse_file(consensus_file), length=num_lines) as bar:
            for relay in bar:
                if relay is not None and relay.address is not None and 'Running' in relay.flags:

                    json_url = location_service_url + relay.address
                    request_start_time = int(round(time.time() * 1000))
                    response = urllib.urlopen(json_url)

                    try:
                        data = json.loads(response.read())
                    except Exception as err:
                        pass

                    try:
                        continent_code = '"{}"'.format(data['continent_code'])
                        country_code = '"{}"'.format(data['country_code'])
                        fingerprint = '"{}"'.format(relay.fingerprint)
                        bandwidth = '"{}"'.format(relay.bandwidth)
                    except Exception as err:
                        print err

                    columns = '(fp,continent_code,country_code,bandwidth,above_avg_bw,flag)'

                    bw_flag = 0
                    if 'Exit' in relay.flags:
                        flag = '"exit"'
                        if relay.bandwidth >= avg_bandwidths[2]:
                            bw_flag = 1
                    elif 'Guard' in relay.flags:
                        flag = '"guard"'
                        if relay.bandwidth >= avg_bandwidths[0]:
                            bw_flag = 1
                    else:
                        flag='"relay"'
                        if relay.bandwidth >= avg_bandwidths[1]:
                            bw_flag = 1

                    avg_bw_flag = '"{}"'.format(bw_flag)

                    try:
                        yield dbpool.runQuery('INSERT INTO {}.fingerprints {} VALUES ({},{},{},{},{},{});'.format(
                            db_name,
                            columns,
                            fingerprint,continent_code,country_code, bandwidth, avg_bw_flag, flag))

                    except Exception as err:
                        print('Problem writing to db: ',err)

@defer.inlineCallbacks
def truncate_table(dbpool, db_name):
    """
    Compute the average bandwidths of guards, relays, and exits in the prior set
    of consensus fingerprints. We'll use this information later as a threshold
    to assign an "above average" flag for updated entries.

    Because we only want the latest consensus data old entries are removed from
    the table as soon as we got our average bandwidth values.

    Arguments:
        dbpool: connection to database
        db_name: database name
    """
    bandwidths_guard = yield dbpool.runQuery('SELECT bandwidth FROM {}.fingerprints WHERE flag="guard";'.format(db_name))
    bandwidths_relay = yield dbpool.runQuery('SELECT bandwidth FROM {}.fingerprints WHERE flag="relay";'.format(db_name))
    bandwidths_exit = yield dbpool.runQuery('SELECT bandwidth FROM {}.fingerprints WHERE flag="exit";'.format(db_name))

    yield dbpool.runQuery('TRUNCATE TABLE {}.fingerprints;'.format(db_name))

    try:
        avg_guards = sum(x[0] for x in bandwidths_guard) / len(bandwidths_guard)
        avg_guards = avg_guards / 2
    except:
        avg_guards = 0
    try:
        avg_relays = sum(x[0] for x in bandwidths_relay) / len(bandwidths_relay)
        avg_relays = avg_relays / 2
    except:
        avg_relays = 0
    try:
        avg_exits = sum(x[0] for x in bandwidths_exit) / len(bandwidths_exit)
        avg_exits = avg_exits / 2
    except:
        avg_exits = 0

    returnValue([avg_guards,avg_relays,avg_exits])

def get_consensus_file(consensus_path):
    """
    Downloads the first consensus file of the current day and saves it in the
    directory specified in the consensus_path. We use the relay descriptors
    consensus data.

    To use more recent files instead of the day's first adjust the strftime
    parsing in now = now.strftime("%Y-%m-%d-00-00-00"):
        consensus is updated every hour
        minutes and seconds remain 00-00

    Arguments:
        consensus_path: relative path to consensus directory, includes the
            output filename for the downloaded consensus file
    """

    base_url = 'https://collector.torproject.org/recent/relay-descriptors/consensuses/'

    now = datetime.datetime.now()
    now = now.strftime("%Y-%m-%d-00-00-00")

    consensus_url = '{base_url}{now}-consensus'.format(base_url=base_url, now=now)

    try:
        download = urllib.URLopener()
        download.retrieve(consensus_url, consensus_path)

    except Exception as err:
        print 'Request failed: ', err, ' URL was ', consensus_url

@click.command()
@click.option('--consensus-path', default=None, type=str, help='path to consensus file')
@click.option('--db-name', default=None, type=str, help='Name of DB')
@click.option('--db-user', default=None, type=str, help='Username DB')
@click.option('--db-passwd', default=None, type=str, help='Password DB')
@click.option('--db-port', default=None, type=int, help='DB connection port')
@click.option('--db-host', default=None, type=str, help='DB connection host')
def main(consensus_path, db_name, db_user, db_passwd, db_port, db_host):
    from twisted.internet import reactor

    dbpool = adbapi.ConnectionPool('MySQLdb', host=db_host, db=db_name, user=db_user, passwd=db_passwd, port=db_port)

    d = write_fingerprints(reactor, dbpool, db_name, consensus_path)
    d.addCallback(lambda ign: reactor.stop())

    reactor.run()

if __name__ == '__main__':
    main()
