import boto3


# region = 'ap-southeast-1'
client = boto3.client('ec2')

spot_pricing = client.describe_spot_price_history(InstanceTypes=["c5.2xlarge"])['SpotPriceHistory']
print type(spot_pricing)  #, spot_pricing.keys()
# print spot_pricing['SpotPriceHistory']
for elem in spot_pricing:
    print elem['AvailabilityZone'], elem['InstanceType'], elem['SpotPrice']
print len(spot_pricing)
# AvailabilityZone="ap-southeast-1a"


# data = client.describe_spot_price_history(InstanceTypes=['c4.4xlarge'])