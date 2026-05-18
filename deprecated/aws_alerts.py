import boto3

negate = ["TERMINATED_WITH_ERRORS", "TERMINATED"]


def find_waiting_emr():
    '''
    Finds waiting emr
    '''
    emr = boto3.client('emr')
    clusters = emr.list_clusters()
    cluster = clusters['Clusters']
    print (len(cluster))
    for elem in cluster:
        emr_state = elem['Status']['State']
        if (emr_state == "WAITING"):
            print (elem['Id'], elem['Name'], elem['Status']['State'], elem['NormalizedInstanceHours'], "\n")


def find_unused_volumes():
    '''
    Finds unused volumes and reports it in slack
    '''
    pass


def find_underutilized_resources():
    '''
    Finds underutilized resources and updates the same in slack
    '''


def send_to_slack(message):
    '''
    Send the message to slack
    '''
