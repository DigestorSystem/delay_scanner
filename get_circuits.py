#!/usr/bin/env/python

from twisted.enterprise import adbapi
from twisted.internet import defer

import click
import random

def form_circuits(guard_tuples, relay_tuples, exit_tuples):
    """
    Receive the lists of guards, middle relays, and exits from the fingerprints
    table and form random circuits from them. Full circuits are written to the
    circuits table to be used later on.

    We limit the number of middle relay variations so we only get guard_limit
    variations per exit and guard. To use an exhaustive creation of circuits
    remove the guard_limit. This is only reasonable when testing *all* circuits
    in connect_tor.py.

    Building circuits works as follows:
        - create a randomly shuffeled list from the set of fingerprints to avoid
        repetitions
        - we want to keep the exit node fixed as long as possible
        - we want variation in the middle relays and the entry guards
            - when using a new circuit for a measurement we want to make sure this
            is a new guard (avoid repeated connections through the same guard)
            - variation of middle relays provides better randomness for
            repetitions in one strategy and parameter set

    Arguments:
        guard_tuples: set of guard fingerprints from the database
        relay_tuples: set of middle relay fingerprints
        exit_tuples: set of exit relay fingerprints
    """
    guards = []
    relays = []
    exits = []

    for elem in guard_tuples:
        guards.append([elem[0], elem[1]])
    for elem in relay_tuples:
        relays.append([elem[0], elem[1]])
    for elem in exit_tuples:
        exits.append([elem[0], elem[1]])

    guards = filter(lambda x:x[1] == 1, guards)
    relays = filter(lambda x:x[1] == 1, relays)
    exits = filter(lambda x:x[1] == 1, exits)

    random.shuffle(guards)
    random.shuffle(relays)
    random.shuffle(exits)

    circuits = []

    guard_index = 0
    relay_index = 0
    guard_limit = len(guards)
    relay_limit = len(relays)

    var_limit = min(guard_limit, relay_limit) - 2

    circuit_counter = 0
    circuit_limit = 1000
    for exit_node in exits:
        guard_index = 0
        relay_index = 0

        while guard_index < var_limit:
            guard_fp = guards[guard_index][0]
            relay_fp = relays[relay_index][0]

            circuit = [guard_fp, relay_fp, exit_node[0]]
            circuits.append(circuit)

            guard_index = guard_index + 1
            relay_index = relay_index + 1

            circuit_counter = circuit_counter + 1

        if circuit_counter >= circuit_limit:
            break

    return circuits

@defer.inlineCallbacks
def write_circuits(dbpool, db_name):
    """
    Use fingerprints from database and form circuits according to all strategies
    that are documented here.

    Strategies:
        continent_code:
        Restrict the selection of relays to a specific continent. We use all 5
        continents for this selection.

        country_code:
        Restrict the selection of relays to a specific country. We use the top
        ten countries that offer relay nodes in the Tor network (with respect to
        the total number of relays).
    """
    strategies = ['continent_code', 'country_code']

    for strategy in strategies:
        print('Processing Strategy', strategy)

        random_flag = 0
        if strategy == 'continent_code':
            selections = ['"EU"', '"NA"', '"OC"', '"SA"', '"AS"']
        elif strategy == 'country_code':
            selections = ['"DE"', '"US"', '"FR"', '"NL"', '"RU"', '"GB"', '"CA"', '"CH"', '"UA"', '"SE"']
        else:
            selections = ['']
            random_flag = 1

        for selection in selections:
            if random_flag == 1:
                selection_query = 'WHERE'
            else:
                selection_query = 'WHERE {} = {} AND'.format(strategy, selection)

            try:
                guards = yield dbpool.runQuery('SELECT fp, above_avg_bw FROM {}.fingerprints {} flag = "guard";'.format(
                    db_name, selection_query))
            except Exception as err:
                print('Problem retrieving guards')

            try:
                relays = yield dbpool.runQuery('SELECT fp, above_avg_bw FROM {}.fingerprints {} flag = "relay"'.format(
                    db_name, selection_query))
            except Exception as err:
                print('Problem retrieving relays')

            try:
                exits = yield dbpool.runQuery('SELECT fp, above_avg_bw FROM {}.fingerprints {} flag = "exit"'.format(
                    db_name, selection_query))
            except Exception as err:
                print('Problem retrieving exits')

            try:
                circuits = form_circuits(guards, relays, exits)
            except Exception as err:
                print('Could not retrieve circuits because ', err)

            columns = 'entry_relay, middle_relay, exit_relay, strategy, geo_code'
            quote = '"'
            strategy_format = '{}{}{}'.format(quote, strategy, quote)

            for circuit in circuits:
                guard_fp = '"{}"'.format(circuit[0])
                relay_fp = '"{}"'.format(circuit[1])
                exit_fp = '"{}"'.format(circuit[2])

                try:
                    yield dbpool.runQuery('INSERT INTO {}.circuits ({}) VALUES ({},{},{},{},{});'.format(
                        db_name,
                        columns,
                        guard_fp,relay_fp,exit_fp, strategy_format, selection))

                except Exception as err:
                    print('Error in writing circuits ', err)

@click.command()
@click.option('--db-name', default=None, type=str, help='Name of DB')
@click.option('--db-user', default=None, type=str, help='Username DB')
@click.option('--db-passwd', default=None, type=str, help='Password DB')
@click.option('--db-port', default=None, type=int, help='DB connection port')
@click.option('--db-host', default=None, type=str, help='DB connection host')
def main(db_name, db_user, db_passwd, db_port, db_host):
    from twisted.internet import reactor

    dbpool = adbapi.ConnectionPool('MySQLdb', host=db_host, db=db_name, user=db_user, passwd=db_passwd, port=db_port)

    d = write_circuits(dbpool, db_name)
    d.addCallback(lambda ign: reactor.stop())

    reactor.run()

if __name__ == '__main__':
    main()
