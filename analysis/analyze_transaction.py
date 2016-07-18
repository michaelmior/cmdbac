#!/usr/bin/env python
import os, sys
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(os.path.join(os.path.dirname(__file__), os.pardir, "core"))

import re
import csv
from utils import filter_repository, dump_all_stats

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cmudbac.settings")
import django
django.setup()

from library.models import *

TRANSACTION_DIRECTORY = 'transactions'

def action_stats(directory = '.'):
    stats = {'action_query_count': {}}

    for repo in Repository.objects.exclude(latest_successful_attempt = None):
        if filter_repository(repo):
            continue

        project_type_name = repo.project_type.name
        if project_type_name not in stats['action_query_count']:
            stats['action_query_count'][project_type_name] = []
        
        for action in Action.objects.filter(attempt = repo.latest_successful_attempt):
            query_count = len(Query.objects.filter(action = action))
            if query_count > 0:
                stats['action_query_count'][project_type_name].append(query_count)

            
    dump_all_stats(directory, stats)

def transaction_stats(directory = '.'):
    stats = {'transaction_count': {}, 'transaction_query_count': {}, 'transaction_read_count': {}, 'transaction_write_count': {}}

    for repo in Repository.objects.exclude(latest_successful_attempt = None):
        if filter_repository(repo):
            continue
        
        project_type_name = repo.project_type.name
        if project_type_name not in stats['transaction_count']:
            stats['transaction_count'][project_type_name] = []
        if project_type_name not in stats['transaction_query_count']:
            stats['transaction_query_count'][project_type_name] = []
        if project_type_name not in stats['transaction_read_count']:
            stats['transaction_read_count'][project_type_name] = []
        if project_type_name not in stats['transaction_write_count']:
            stats['transaction_write_count'][project_type_name] = []
        

        for action in Action.objects.filter(attempt = repo.latest_successful_attempt):
            transaction = ''
            query_count = 0
            transaction_count = 0

            for query in Query.objects.filter(action = action):
                if 'BEGIN' in query.content.upper() or 'START TRANSACTION' in query.content.upper():
                    transaction = query.content + '\n'
                    query_count = 1
                elif transaction != '':
                    transaction += query.content + '\n'
                    query_count += 1
                    if 'COMMIT' in query.content.upper():
                        transaction = transaction.strip('\n')
                    
                        # for each transaction, count the number of transactions
                        transaction_count += 1

                        # for each transaction, count the number of read/write
                        read_count = len(re.findall('SELECT', transaction.upper()))
                        stats['transaction_read_count'][project_type_name].append(read_count)
                        write_count = 0
                        for keyword in ['INSERT', 'DELETE', 'UPDATE']:
                            write_count += len(re.findall(keyword, transaction.upper()))
                        stats['transaction_write_count'][project_type_name].append(write_count)
                        
                        # for each transaction, count the queries
                        query_count -= 2
                        stats['transaction_query_count'][project_type_name].append(query_count)

                        try:
                            print repo.name
                            print transaction
                            print
                            print
                        except:
                            pass

                        transaction = ''

            if transaction_count > 0:
                stats['transaction_count'][project_type_name].append(transaction_count)

            
    dump_all_stats(directory, stats) 

def blind_write():
    total = 0
    count = 0

    def is_write(query):
        return ('INSERT' in query or 'UPDATE' in query) and ('UTC LOG:  ' not in query)

    transaction = []
    line = sys.stdin.readline().strip()
    while line:
        repo_name = line
        
        line = sys.stdin.readline().strip()
        while True:
            if line.upper() == 'BEGIN':
                transaction = []
                total += 1
            elif line.upper() == 'COMMIT':
                is_writes = []
                for i in xrange(len(transaction)):
                    if is_write(transaction[i]):
                        is_writes.append(i)
                if len(is_writes) > 1:
                    print 'REPO: ', repo_name
                    for i in is_writes:
                        print transaction[i]
                    print
                sys.stdin.readline()
                sys.stdin.readline()
                break
            else:
                transaction.append(line)

            line = sys.stdin.readline().strip()

        line = sys.stdin.readline()

    print 'Total # of Transactions:', total
    print 'Total # of Blind Writes:', count

def main():
    # active
    # action_stats(TRANSACTION_DIRECTORY)
    # transaction_stats(TRANSACTION_DIRECTORY)
    blind_write()
    
    # working
    
    # deprecated
if __name__ == '__main__':
    main()
