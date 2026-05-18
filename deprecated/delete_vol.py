import boto3

ec2 = boto3.resource('ec2', region_name='ap-south-1')
# volumes = ec2.volumes.all() # If you want to list out all volumes
volumes = ec2.volumes.filter(
    Filters=[{'Name': 'status', 'Values': ['available']}])
for volume in volumes:
    print ("Deleting the volume ", volume)
    volume.delete()
