#!/usr/bin/env/python

#from __future__ import print_function
from twisted.internet import defer
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.enterprise import adbapi

from twisted.python import log

import sys
import random
import txtorcon
import click
import time

class SuccessStatistics():
    """
    Track the success of building circuits. We use this to increment the
    success counter circuit_success_cnt whenever a circuit_built event was
    triggered. Whenever build_circuit does not deliver a valid circuit, we
    increment the fail counter circuit_fail_cnt.
    """
    def __init__(self):
        self.circuit_fail_cnt = 0
        self.circuit_success_cnt = 0

    def circuit_failed(self):
        self.circuit_fail_cnt += 1

    def circuit_succeeded(self):
        self.circuit_success_cnt += 1

class CircuitLogger(txtorcon.StreamListenerMixin,
                          txtorcon.CircuitListenerMixin):
    """
    Listen to events and measure timing. We use this to count the number of
    fails and successful circuit builds.
    """
    def __init__(self):
        self.circuit_new_time = 0
        self.circuit_built_diff = 0

    def circuit_new(self, circuit):
        new_time = int(round(time.time() * 1000))

        self.circuit_new_time = new_time

    def circuit_built(self, circuit):
        built_time = int(round(time.time() * 1000))
        built_diff = built_time - self.circuit_new_time

        self.circuit_built_diff = built_diff

@defer.inlineCallbacks
def write_results(dbpool, db_name, strategy, geo_code, period, repetitions, request_timing, circuit_build_timing, circuit_fail_cnt, circuit_success_cnt):

    db_cols_circ = '(build_offset, strategy, geo_code, period)'
    db_cols_req = '(request_offset, strategy, geo_code, period)'
    db_cols_err = '(strategy, geo_code, period, rate, repetitions)'

    quote ='"'
    period_string = '{}{}{}'.format(quote,period,quote)
    print period_string

    for time in circuit_build_timing:
        time_string = '{}{}{}'.format(quote, time, quote)

        try:
            yield dbpool.runQuery('INSERT INTO {}.circuit_statistics {} VALUES ({},{},{},{});'.format(
                db_name,
                db_cols_circ,
                time_string,strategy,geo_code,period_string))
        except Exception as err:
            print('Unable to write circ timing to db: ', err)
            pass

    for time in request_timing:
        time_string = '{}{}{}'.format(quote, time, quote)

        try:
            print('INSERT INTO {}.request_statistics {} VALUES ({},{},{},{});'.format(
                db_name,
                db_cols_req,
                time_string,strategy,geo_code,period_string))
            yield dbpool.runQuery('INSERT INTO {}.request_statistics {} VALUES ({},{},{},{});'.format(
                db_name,
                db_cols_req,
                time_string,strategy,geo_code,period_string))
        except Exception as err:
            print('Unable to write req timing to db: ', err)
            pass

    rate = '"{}"'.format(circuit_fail_cnt)
    rep_string = '"{}"'.format(repetitions)
    try:
        yield dbpool.runQuery('INSERT INTO {}.circuit_failures {} VALUES ({},{},{},{},{});'.format(
            db_name,
            db_cols_err,
            strategy,geo_code, period_string, rate, rep_string))
    except Exception as err:
        print('Unable to write errors to db: ', err)
        pass

    print('Results for {gc}: {c_time} circ timing, {r_time} req timing, {cf} circ failures, {cs} circ successes.'.format(
        gc = geo_code,
        c_time = len(circuit_build_timing),
        r_time = len(request_timing),
        cf = circuit_fail_cnt,
        cs = circuit_success_cnt))

    circuit_fail_cnt = 0
    circuit_success_cnt = 0

@inlineCallbacks
def get_circuit(strategy, geo_code, dbpool, db_name, state):
    relays = []
    try:
        circuits_tuple = yield dbpool.runQuery('SELECT * FROM {}.circuits WHERE strategy = {} AND geo_code = {};'.format(
            db_name, strategy, geo_code))
    except Exception as err:
        print('Error retrieving circuits: ', err)

    try:
        circuits = list(circuits_tuple)
        random.shuffle(circuits)

        relays = [circuits[0][1], circuits[0][2], circuits[0][3], circuits[0][5]]
    except Exception as err:
        pass

    returnValue(relays)

@defer.inlineCallbacks
def connect_tor(reactor, tor_control, socks, dbpool, db_name, strategy, geo_code, repetitions, period):
    """
    Manages the building of circuits and sends n Bytes requests to our local
    server.

    Arguments:
        reactor: inline callback reactor object from import in main
        tor_control: control port, read in options
        socks: socks port, read in options
        dbpool: connection to database
        db_name: whatever name you have your database
        strategy: current strategy for the selection of circuits
        geo_code: specification of where the circuit will be built, follows the
            strategy
        repetitions: this many random repetitions are made for one set of
            strategy and geo_code
        period: time of the day according to your local time zone, can be 'da'
            for daytime (6am - 6pm) or 'ni' for nighttime (6pm - 6am)
    """
    strategy_string = '"{}"'.format(strategy)
    geo_string = '"{}"'.format(geo_code)

    control_port = TCP4ClientEndpoint(reactor, 'localhost', int(tor_control))
    socks_port = TCP4ClientEndpoint(reactor, 'localhost', int(socks))

    cnt = 0
    attempt_limit = 5
    while cnt < attempt_limit:
        try:
            tor = yield txtorcon.connect(reactor,control_port)
            state = yield tor.create_state()

            statistics = SuccessStatistics()
            listener = CircuitLogger()
            state.add_circuit_listener(listener)

            circuit_build_timing = []
            request_timing = []

            circuit_fail_cnt = 0
            circuit_success_cnt = 0

            for repetition in xrange(1,repetitions+1):
                if strategy == 'weighted':
                    while True:
                        try:
                            circ = yield state.build_circuit()
                            yield circ.when_built()

                            circuit_build_timing.append(listener.circuit_built_diff)
                            statistics.circuit_succeeded()
                        except Exception as err:
                            statistics.circuit_failed()
                            continue

                        break
                else:
                    while True:
                        circuit_data = yield get_circuit(strategy_string, geo_string, dbpool, db_name, state)
                        relays = [circuit_data[0],circuit_data[1],circuit_data[2]]

                        try:
                            circ = yield state.build_circuit(relays,using_guards=False)
                            yield circ.when_built()

                            circuit_build_timing.append(listener.circuit_built_diff)
                            statistics.circuit_succeeded()

                        except Exception as err:
                            statistics.circuit_failed()
                            continue

                        break

                if True:
                    successful = 1
                    avg_request_time = 0
                    num_repetitions = 50

                    """
                    For the requests you'll need a web server. Example: run apache and provide
                    a random binary file for download.
                    We used a 500 Bytes bin file.
                    """

                    print('Repeat 50 Requests now')
                    for i in xrange(0,num_repetitions):
                        try:
                            uri = '' #BLINDED FOR SUBMISSION
                            agent = circ.web_agent(reactor, socks_port)

                            request_start_time = int(round(time.time() * 1000))
                            resp = yield agent.request(b'GET', uri)

                            request_end_time = int(round(time.time() * 1000))
                            request_delta = request_end_time - request_start_time

                            avg_request_time = avg_request_time + request_delta
                        except Exceptions as err:
                            print('Error in request: ', err)

                            yield circ.close()
                            successful = 0
                            break

                    if successful == 1:
                        avg_request_time = float(avg_request_time) / float(num_repetitions)
                        request_timing.append(avg_request_time)
                        yield circ.close()

        except Exception as err:
            circuit_fail_cnt += 1
            cnt += 1
            continue
        break

    try:
        yield write_results(dbpool, db_name, strategy_string, geo_string, period, repetitions, request_timing, circuit_build_timing, circuit_fail_cnt, circuit_success_cnt)
    except Exception as err:
        print('Failure writing results:', err)

@click.command()
@click.option('--tor-control', default=None, type=int, help='tor control port from torrc config')
@click.option('--socks', default=None, type=int, help='socks procy from torrc config')
@click.option('--db-name', default=None, type=str, help='Name of DB')
@click.option('--db-user', default=None, type=str, help='Username DB')
@click.option('--db-passwd', default=None, type=str, help='Password DB')
@click.option('--db-port', default=None, type=int, help='DB connection port')
@click.option('--db-host', default=None, type=str, help='DB connection host')
@click.option('--strategy', default=None, type=str, help='choose continent_code or country_code')
@click.option('--geo-code', default=None, type=str, help='choose continent or country according to srategy')
@click.option('--repetitions', default=10, type=int, help='Number of repetitions per parameter combination')
@click.option('--period', default=None, type=str, help='enter [da] (6am - 6pm) or [ni] (6pm - 6am)')
def main(tor_control, socks, db_name, db_user, db_passwd, db_port, db_host, strategy, geo_code, repetitions, period):
    from twisted.internet import reactor

    dbpool = adbapi.ConnectionPool('MySQLdb', host=db_host, db=db_name, user=db_user, passwd=db_passwd, port=db_port)

    d = connect_tor(reactor, tor_control, socks, dbpool, db_name, strategy, geo_code, repetitions, period)
    d.addCallback(lambda ign: reactor.stop())

    reactor.run()

if __name__ == '__main__':
    main()
