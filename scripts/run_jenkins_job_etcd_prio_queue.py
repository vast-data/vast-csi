#!/usr/bin/python3 -u

import argparse
import jenkinsapi
from jenkinsapi.utils.crumb_requester import CrumbRequester
import etcd
import time
import sys
import os
from concurrent.futures import ThreadPoolExecutor
import re
import urllib
import shlex
import random

random.seed()

supported_algorithms = ['ignore', 'decending', 'q_decending']

T_pool = ThreadPoolExecutor(max_workers=10)
'''
Global Thread pool
'''

wait_to_run = True
'''
This variable wymbole that the jenkins job related with this 
code is wating to run.
'''
wait_future = None
'''
Global wating future variable 
'''

global_prefix = ''
'''
The global prefix where to store/read etcd objects from
'''

last_msg = ''

LOCK_TTL = 300

RND_SLEEP = 10


def print_msg_once(msg):
    global last_msg
    if last_msg == msg:
        return
    last_msg = msg
    print(msg)


def parse_args():
    """PArse the arguments given by the user

    :returns: The parsed arguments object
    :rtype: argparse.ArgumentParser

    """
    parser = argparse.ArgumentParser(
        description='Wait to run jenkins job use ETCD as FIFO queue')
    parser.add_argument(
        '--jenkins-server',
        help='The jenkins server http/https url',
        required=True,
        dest='jenkins_server')
    parser.add_argument(
        '--jenkins-password',
        help='The pasword to use for jenkins connection',
        required=False,
        dest='jenkins_password')
    parser.add_argument(
        '--jenkins-user',
        help='The jenkins user to use',
        required=False,
        dest='jenkins_user')
    parser.add_argument(
        '--jenkins-job-name',
        help='The jenkins job name to run',
        required=True,
        dest='jenkins_job_name')
    parser.add_argument(
        '--blocking',
        required=False,
        default=False,
        help='Wait for the jenkins job to finish',
        dest='blocking',
        action='store_true')
    parser.add_argument(
        '--disable-etcd-locking',
        required=False,
        action='store_true',
        default=False,
        dest='disable_etcd_locking')
    parser.add_argument(
        '--object-name',
        help='The name of the object to add to the queue',
        required=False,
        dest='object_name')
    parser.add_argument(
        '--etcd-server',
        help='The ETCD server ti use as a Queue',
        default='127.0.0.1',
        required=False,
        dest='etcd_server')
    parser.add_argument(
        '--etcd-port',
        help='The etcd server port to connect to',
        type=int,
        default=2379,
        required=False,
        dest='etcd_port')
    parser.add_argument(
        '--lock-ttl',
        help='The TTL of the loack o aquire',
        type=int,
        default=15,
        required=False,
        dest='lock_ttl')
    parser.add_argument(
        '--etcd-prefix',
        help='A prefix to use with etcd default path',
        type=str,
        default='',
        required=True,
        dest='etcd_prefix')
    parser.add_argument(
        '--base-queue-prefix',
        help='A prefix to use with etcd default path',
        type=str,
        default='',
        required=True,
        dest='base_queue_prefix')
    parser.add_argument(
        '--object-renew-timeout',
        help=
        'The amount of seconds before an object have nore renewed it\'s record',
        type=int,
        default=600,
        required=False,
        dest='object_life')
    parser.add_argument('jenkins_job_params', nargs='+')

    parsed_args = parser.parse_args()
    return parsed_args, parser


def get_queue_root(prefix, parsed_args):
    """Return the root of all the queues 

    :returns: 
    :rtype: 

    """
    global global_prefix

    if parsed_args.etcd_prefix:
        return os.path.dirname(global_prefix)
    return global_prefix


def get_queue_name():
    global global_prefix
    return os.path.basename(global_prefix)


def _lock_object(etcd_client, lock, lock_name, lock_ttl=LOCK_TTL):
    """Lock an objet which leads to queue locking 

    :param lock_name: The lock object name.
    :param lock_ttl: the lock ttl.
    :returns: The cloked object.
    :rtype: etcd.Lock
    """
    '''
    check if the object exists if not create is than lock.
    '''

    try:
        lock.acquire(lock_ttl=lock_ttl)
        if lock.is_acquired:
            return True
        #if we dont aquire the lock we release it to prevent it from
        #causing lock does not exists issues and will try later
        lock.release()
        return False
    except etcd.EtcdLockExpired:
        print('Lock has expired retry to lock')
        return False


def renew_lock(lock, retry_loop=5, lock_ttl=LOCK_TTL):
    while lock.is_acquired:
        lock.acquire(lock_ttl=lock_ttl)
        time.sleep(retry_loop)
    print('lock released')


def get_root_lock(etcd_client):
    lock = etcd.Lock(etcd_client, lock_name='root')
    return lock


def lock_root(etcd_client, lock_ttl=300, queue_root='root', lock=None):
    """Lock the root of all queus 

    :param queue_root: The root queue name.
    :param etcd_client: The etcd client object.
    :returns: An aquiered root.
    :rtype: etcd.Lock

    """
    if lock is None:
        '''
        Renew the lock if it was given
        '''
        lock = get_root_lock(etcd_client=etcd_client)
    return _lock_object(
        etcd_client=etcd_client, lock_name=queue_root, lock=lock)


def renew_root_lock(etcd_client, lock, retry_loop=5):
    while lock.is_acquired:
        lock_root(etcd_client=etcd_client, lock=lock)
        time.sleep(retry_loop)
    print('lock released')


def list_queues(etcd_client, root_prefix):
    """List Valid queues under the root prefix which is  adirectory
    A queue is a directory which have.
    1) a sub directory called jobs 
    2) a key called score ( if no such exists the key is considered -1.
    3) a key called algorithm if not given than ignore is the default.

    :param etcd_client: The etcd client.
    :param root_prefix: The prefix.
    :returns: List of queues with the queue score and jobs 
    :rtype: list.

    """
    queues = {}
    res = etcd_client.read(root_prefix)
    for child in res.children:
        if child.dir:
            _queue_name = os.path.basename(child.key)
            if not _queue_name:
                continue
            _queue = {}
            '''
            Queues are represented by directories
            '''
            try:
                jobs = etcd_client.read(os.path.join(child.key, 'jobs'))
            except etcd.EtcdKeyNotFound:
                #if keys does not exists this is not a queue
                continue

            if not jobs.dir:
                #jobs must be a dir
                continue
            #if we got here this is a queue
            score = -1
            algorithm = 'ignore'
            try:
                _score = etcd_client.read(os.path.join(child.key,
                                                       'score')).value
                _score = int(_score)
                score = _score
            except etcd.EtcdKeyNotFound:
                # key not found we keep the default
                pass
            except ValueError:
                #key is not an integet we keep the default value
                pass

            try:
                algorithm = etcd_client.read(
                    os.path.join(child.key, 'algorithm')).value
                if algorithm not in supported_algorithms:
                    #we only support algorithms found in the list.
                    pass
            except etcd.EtcdKeyNotFound:
                # key not found we keep the default
                pass
            _queue['length'] = len(jobs._children)
            _queue['score'] = score
            _queue['algorithm'] = algorithm
            queues[_queue_name] = _queue
    return queues


def check_queue_avaliability(etcd_client, queue_name, root_prefix):
    """Check All The queues to see if we have prmissions to run.
    The conditions to run are:
    1) This Queue has the higest score 
    2) This Queue does not have the higest score but other 
       queues are empty.
    
    :param etcd_client: The etcd client.
    :param root_prefix: The root prefix of all queues.
    :returns: None.
    :rtype: None

    """
    queues = list_queues(etcd_client=etcd_client, root_prefix=root_prefix)
    properties = queues[queue_name]
    if properties['score'] < 0:
        '''
        Negative score means that the queue is disabled
        '''
        print_msg_once('Queue is currently blocked with score of "%s"' %
                       properties['score'])
        return False
    for q_name, q_props in queues.items():
        if q_name == queue_name:
            continue
        if (properties['score'] < q_props['score']) and (q_props['length'] >
                                                         0):
            return False
    return True


def sanity_check(parsed_args, parser):
    """Do some sanity check for given attributes

    :param parsed_args: The arguments parsed
    :returns: 
    :rtype: 

    """

    def _print_and_exit(message=''):
        print(message)
        parser.print_help()
        sys.exit(1)

    if (not parsed_args.disable_etcd_locking) and (parsed_args.object_name is
                                                   None):
        _print_and_exit('When using etcd --object-name must be define')
    '''
    Check the the format of the jenkins job params hiven is at x=y
    '''

    if 'jenkins_job_params' in parsed_args:
        param_pattern = re.compile('(\w)+=')
        for param in parsed_args.jenkins_job_params:
            if not param_pattern.match(param):
                _print_and_exit(
                    'All params passed to a jenkins job must be at the format of X=Y %s is not at this format'
                    % param)
    if parsed_args.base_queue_prefix == '':
        _print_and_exit(
            '--base-queue-prefix and cont be provided with empty value')
    if parsed_args.etcd_prefix == '':
        _print_and_exit('--etcd-prefix can not be given an empty value')


def get_jenkins_object(jenkins_server, username=None, password=None):
    """Return a jenkins object which configured to
       A specifc jenkins server.

    :param jenkins_server: The <hostname/ip>[:<port>] of the jenkins server.
    :param username: User name to use.
    :param password: password to use.
    :returns: jenkinsapi.jenkins.Jenkins object.
    :rtype: jenkinsapi.jenkins.Jenkins

    """

    requester = CrumbRequester(
        baseurl=jenkins_server, username=username, password=password)
    j_obj = jenkinsapi.jenkins.Jenkins(
        jenkins_server,
        requester=requester,
        username=username,
        password=password)
    return j_obj


def check_jenkins_nodes_avaliability(jenkins_obj, valid_nodes):
    """Return A list of avaliable jenkins server which can run 
    The job , but those nodes must be in the valid_nodes section

    :param jenkins_obj: The jenkins connection object.
    :param valid_nodes: A list of valid nodes 
    :returns: 
    :rtype: 

    """
    jenkins_nodes = jenkins_obj.get_nodes()
    avaliable_node = []
    for j_node in set(jenkins_nodes.keys()).intersection(valid_nodes):
        try:
            node_data = jenkins_obj.get_node(j_node)
            if node_data.is_online() and node_data.is_idle():
                avaliable_node.append(j_node)
        except:
            print('Failed to get information on node %s' % j_node)
    return avaliable_node


def create_etcd_client(etcd_host, etcd_port):
    client = etcd.Client(host=etcd_host, port=etcd_port, allow_reconnect=True)
    return client


def get_root_prefix(prefix):
    return os.path.dirname(prefix)


def get_jenkins_valid_nodes_list(etcd_client, prefix='jenkins_nodes/'):
    """Read the list of node names from etcd which will be checked for avaliability

    :param etcd_client: etcd client object.
    :returns: list of valid node names
    :rtype: list

    """
    global global_prefix
    valid_nodes = []
    try:
        prefix = os.path.join(global_prefix, prefix)
        res = etcd_client.read(prefix)
        for child in res.children:
            node_name = child.key[len(prefix):]
            valid_nodes.append(node_name)
    except etcd.EtcdKeyNotFound:
        '''
        We got here is means that the path was not updated yet still no need to fail
        '''
        return []
    return valid_nodes


def get_queue_jenkins_valid_nodes_list(etcd_client, prefix='jenkins_nodes/'):
    """Read the list of node names from etcd which will be checked for avaliability

    :param etcd_client: etcd client object.
    :returns: list of valid node names
    :rtype: list

    """
    global global_prefix
    valid_nodes = []
    try:
        prefix = os.path.join(get_root_prefix(global_prefix), prefix)
        res = etcd_client.read(prefix)
        for child in res.children:
            node_name = child.key[len(prefix):]
            valid_nodes.append(node_name)
    except etcd.EtcdKeyNotFound:
        '''
        We got here is means that the path was not updated yet still no need to fail
        '''
        return []
    return valid_nodes


def write_object(etcd_client,
                 object_name,
                 object_ttl,
                 prefix='jobs/',
                 refresh=False):
    """Write An object with a timestamp as value

    :param etcd_client: etcd client object.
    :param object_name: The name of the object to write.
    :param object_ttl: The object ttl in seconds before it is removed.
    :param prefix: the etcd prefix.
    :returns: 
    :rtype: 

    """
    global global_prefix
    prefix = os.path.join(global_prefix, prefix)
    full_object_name = os.path.join(prefix, object_name)
    if refresh:
        etcd_client.refresh(full_object_name, ttl=object_ttl)
    else:
        etcd_client.write(full_object_name, time.time(), ttl=object_ttl)


def _queue_algorithm_ignore(etcd_client, queue_prefix):
    return


def _queue_algorithm_decrease(etcd_client, queue_prefix):
    score_prefix = os.path.join(queue_prefix, 'score')
    try:
        score = etcd_client.read(score_prefix).value
    except etcd.EtcdKeyNotFound:
        #no key we ignore
        return
    try:
        score = int(score)
        if score < 0:
            return
        score -= 1
        etcd_client.write(score_prefix, score)
    except ValueError:
        return


def _queue_algorithm_q_decrease(etcd_client, queue_prefix):
    score_prefix = os.path.join(queue_prefix, 'score')
    try:
        score = etcd_client.read(score_prefix).value
    except etcd.EtcdKeyNotFound:
        #no key we ignore
        return
    try:
        score = int(score)
        if (score > 0 and score == 1) or (score == 0):
            score = -1
        elif score > 0:
            score -= 1

        etcd_client.write(score_prefix, score)
    except ValueError:
        return


def run_algorithm(etcd_client, queue_prefix):
    """Run queue algorithm.

    :param etcd_client: The etcd client object.
    :param queue_prefix: the queue prefix.
    :returns: 
    :rtype: 

    """
    algorithm_prefix = os.path.join(queue_prefix, 'algorithm')
    try:
        algorithm = etcd_client.read(algorithm_prefix).value
    except etcd.EtcdKeyNotFound:
        algorithm = 'ignore'
    me = sys.modules[__name__]
    if not hasattr(me, f'_queue_algorithm_{algorithm}'):
        algorithm = 'ignore'
    getattr(me, f'_queue_algorithm_{algorithm}')(etcd_client, queue_prefix)


def write_object_loop(etcd_client, object_name, object_ttl, sleep_time,
                      prefix):
    """A wait loop which keeps on updating etcd object

    :param etcd_client: The etcd client object.
    :param object_name: The object name to update.
    :param object_ttl: The object ttl.
    :param sleep_time: The sleep time.
    :param prefix: The prefix to use.
    :returns: 
    :rtype: 

    """

    def _refresh():
        '''
        A wrapper arount write object.
        '''
        write_object(
            etcd_client=etcd_client,
            object_name=object_name,
            object_ttl=object_ttl,
            prefix=prefix,
            refresh=True)

    global wait_to_run
    '''
    First write the object than enter the loop
    '''
    write_object(
        etcd_client=etcd_client,
        object_name=object_name,
        object_ttl=object_ttl,
        prefix=prefix,
        refresh=False)
    while wait_to_run:
        _refresh()
        time.sleep(sleep_time)


def next_object_in_queue(etcd_client, prefix='jobs/'):
    """Return the next object to be called in the queue.
    we relay here on the object creation index.

    :param etcd_client: the etcd client object.
    :param prefix: the etcd prefix to search.
    :returns: the object id of the next objectto execute.
    :rtype: string

    """

    def sort_by_create(obj):
        return int(obj.createdIndex)

    global global_prefix
    prefix = os.path.join(global_prefix, prefix)
    res = etcd_client.read(prefix)
    sorted_by_index = sorted([c for c in res.children], key=sort_by_create)
    if sorted_by_index:
        return sorted_by_index[0].key[len(prefix):]
    return None


def wait_for_my_turn(etcd_client, parsed_args):
    next_obj = next_object_in_queue(etcd_client=etcd_client)
    queue_name = get_queue_name()
    print(f'Wating for my turn to become the first in  Queue "{queue_name}"')
    while next_obj != parsed_args.object_name:
        '''
        Just wait until it is my turn to execute.
        '''
        next_obj = next_object_in_queue(etcd_client=etcd_client)
        time.sleep(3)
    print(f'I am the next in the running Queue "{queue_name}"')


def delete_object(etcd_client, object_name, prefix='jobs/'):
    """Delete An etcd_object

    :param etcd_client: etcd client object.
    :param object_name: The object e to delete.
    :param prefix: The prefix re of the obct to delete.
    :returns: 
    :rtype: 

    """
    global global_prefix
    prefix = os.path.join(global_prefix, prefix)
    full_object_name = os.path.join(prefix, object_name)
    try:
        etcd_client.delete(full_object_name)
    except etcd.EtcdKeyNotFound:
        print('%s was not found so no delete is needed' % full_object_name)


def jenkins_nodes_avaliable(etcd_client, jenkins_obj):
    valid_nodes = sorted(
        get_queue_jenkins_valid_nodes_list(etcd_client=etcd_client))
    free_jenkins_nodes = check_jenkins_nodes_avaliability(
        jenkins_obj=jenkins_obj, valid_nodes=valid_nodes)
    if free_jenkins_nodes:
        return free_jenkins_nodes[0]
    return None


def run_jenkins_build(parsed_args,
                      jenkins_node,
                      etcd_client,
                      jenkins_obj,
                      prefix='jenkins_nodes/'):
    """Lunch a jenkins job , the function will return only after the job started

    :param parsed_args: The parsed arguments which have been collected from the user.
    :param jenkins_node: The jenkins node on which this job will be executed on.
    :param jenkins_obj: The jenkins object (server)
    :returns:  
    :rtype: jenkins job build
    """
    build_params = {}
    global global_prefix
    try:
        prefix = os.path.join(
            get_root_prefix(global_prefix), prefix, jenkins_node)
        res = etcd_client.read(prefix)
    except:
        print(
            'Failed to run jenkins node on %s , node could not be found at %s'
            % (jenkins_node, prefix))
    extra_build_params = []
    if res.value:
        _params = shlex.split(res.value)
        temp_parser = argparse.ArgumentParser('temp')
        temp_parser.add_argument('extra_build_params', nargs='+')
        _parsed = temp_parser.parse_args(_params)
        if 'extra_build_params' in _parsed:
            extra_build_params = _parsed.extra_build_params

    if 'jenkins_job_params' in parsed_args:
        for param in parsed_args.jenkins_job_params + extra_build_params:
            var, val = param.strip().split('=', 1)
            try:
                val = val % jenkins_node
            except TypeError:
                '''
                We can not convert this means that the job does not contains the %(jenkins_node)s
                '''
            build_params[var] = val

    job = jenkins_obj[parsed_args.jenkins_job_name]
    pending_job = job.invoke(block=False, build_params=build_params)
    print('Wating for job %s' % pending_job)
    if not parsed_args.blocking:
        print('Non-Blocking mode, jenkins job will not be wated for')
        return None
    pending_job.block_until_building()
    return pending_job


def wait_for_jenkins_build(jenkins_obj, jenkins_job):
    """Wait for a jenkins job to finish 

    :param jenkins_obj: The jenkins object (server)
    :param jenkins_job: The  jenkins job object.
    :returns: True if job suceeded    if not build.is_good():
        print('Build job %s Failed' % build.buildno)
        sys.exit(1) False if failed 
    :rtype: boolean

    """
    build = jenkins_job.get_build()
    print('Build %s has started you can follow it at %s' %
          (jenkins_job.get_build_number(), build.baseurl))
    jenkins_job.block_until_complete()
    build = build.job.get_build(build.buildno)
    if not build.is_good():
        print('Build job %s Failed' % build.buildno)
        return False
    return True


def rand_sleep(start, end):
    """Sleep for a random time

    :param start: The minimal value.
    :param end: The end value.
    :returns: 
    :rtype: 

    """
    time.sleep(random.randint(start, end))


def wait_until_queue_can_run(etcd_client, root_prefix, queue_name, jenkins_obj,
                             lock):
    """Wait until this queue can run an launch a jenkins job

    :param etcd_client: The etcd client object.
    :param root_prefix: The root prefix of all queues 
    :param queue_name: the name of this queue.
    :returns: 
    :rtype: 

    """
    while True:
        was_locked = lock_root(etcd_client=etcd_client, lock=lock)
        if was_locked:
            if check_queue_avaliability(
                    etcd_client=etcd_client,
                    queue_name=queue_name,
                    root_prefix=root_prefix):
                #we can run but do are there any jenkins node
                #avaliable.
                jenkins_node = jenkins_nodes_avaliable(
                    etcd_client=etcd_client, jenkins_obj=jenkins_obj)
                if jenkins_node is not None:
                    #if we are here then we dont
                    #release the lock and pass it on
                    print(f'Job will be executed on {jenkins_node}')
                    return jenkins_node
            lock.release()
        else:
            lock.release()

        rand_sleep(10, 20)


def _main():
    """Main Execution Code

    :returns: 
    :rtype: 

    """

    global T_pool
    global wait_future
    global wait_to_run
    global global_prefix

    parsed_args, parser = parse_args()
    sanity_check(parsed_args, parser)
    #chnage the global prefix
    global_prefix = '/%s/%s' % (
        urllib.parse.urlparse(parsed_args.jenkins_server).netloc,
        parsed_args.base_queue_prefix)

    root_prefix = global_prefix
    queue_name = parsed_args.etcd_prefix

    if parsed_args.etcd_prefix:
        #support pools implemanted by prefix
        global_prefix = '%s/%s' % (global_prefix, parsed_args.etcd_prefix)
    if not parsed_args.disable_etcd_locking:
        etcd_client = etcd.Client(
            host=parsed_args.etcd_server, port=parsed_args.etcd_port)
        '''
        Lunch a looping thread which keeps on writing an object.
        '''
        wait_future = T_pool.submit(write_object_loop, etcd_client,
                                    parsed_args.object_name,
                                    parsed_args.object_life, 8, 'jobs/')
        wait_for_my_turn(etcd_client=etcd_client, parsed_args=parsed_args)

    jenkins_obj = get_jenkins_object(
        jenkins_server=parsed_args.jenkins_server,
        username=parsed_args.jenkins_user,
        password=parsed_args.jenkins_password)

    lock = get_root_lock(etcd_client=etcd_client)
    lock_root(etcd_client=etcd_client, lock=lock)

    jenkins_node = wait_until_queue_can_run(
        etcd_client=etcd_client,
        root_prefix=root_prefix,
        queue_name=queue_name,
        jenkins_obj=jenkins_obj,
        lock=lock)

    T_pool.submit(renew_root_lock, etcd_client=etcd_client, lock=lock)

    jenkins_job = run_jenkins_build(
        parsed_args=parsed_args,
        jenkins_node=jenkins_node,
        jenkins_obj=jenkins_obj,
        etcd_client=etcd_client)

    #releaseing the lock should release the entire queue
    lock.release()

    if wait_future is not None:
        '''
        If we are here this means that we have launched a wait loop
        which updates the object in a loop until we stop it.
        '''
        wait_to_run = False
        #wait for the update to finish
        wait_future.result()
        #remove the object allowing other to be first in the queue
        delete_object(
            etcd_client=etcd_client,
            object_name=parsed_args.object_name,
            prefix='jobs/')
    run_algorithm(etcd_client=etcd_client, queue_prefix=global_prefix)
    if parsed_args.blocking:
        if not wait_for_jenkins_build(
                jenkins_obj=jenkins_obj, jenkins_job=jenkins_job):
            print('Jenkins job Failed')
            sys.exit(1)
    print('jenkins job ended sucesfully')


_main()
