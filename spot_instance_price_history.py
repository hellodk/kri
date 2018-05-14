import pandas as pd
from boto3 import client

client = client(service_name='ec2')
prices = client.describe_spot_price_history(InstanceTypes=["m3.medium"],
                                            AvailabilityZone="ap-southeast-1a")
df = pd.DataFrame(prices['SpotPriceHistory'])

df.set_index("Timestamp", inplace=True)
df["SpotPrice"] = df.SpotPrice.astype(float)
df = df.sort_index()

week_ago = pd.datetime.now() - pd.datetools.Day(7)
twice_daily = df.ix[week_ago:].resample("12h")
twice_daily.SpotPrice.plot()

'''
describe_reserved_instances()
describe_reserved_instances_listings()
describe_reserved_instances_modifications()
describe_reserved_instances_offerings()
describe_scheduled_instances()


describe_spot_datafeed_subscription()
describe_spot_fleet_instances()
describe_spot_fleet_request_history()
describe_spot_fleet_requests()
describe_spot_instance_requests()
describe_spot_price_history()
'''