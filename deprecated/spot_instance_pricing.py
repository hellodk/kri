import boto3
import datetime

client = boto3.client('ec2', region_name='us-west-2')
regions = [x["RegionName"] for x in client.describe_regions()["Regions"]]
print "The lit of regions are ", regions

INSTANCE = "p2.xlarge"
print("Instance: %s" % INSTANCE)

results = []

for region in regions:
    client = boto3.client('ec2', region_name=region)
    prices = client.describe_spot_price_history(
        InstanceTypes=[INSTANCE],
        ProductDescriptions=['Linux/UNIX', 'Linux/UNIX (Amazon VPC)'],
        StartTime=(datetime.datetime.now() -
                   datetime.timedelta(hours=4)).isoformat(),
        MaxResults=1
    )
    for price in prices["SpotPriceHistory"]:
        results.append((price["AvailabilityZone"], price["SpotPrice"]))

for region, price in sorted(results, key=lambda x: x[1]):
    print("Region: %s price: %s" % (region, price))
