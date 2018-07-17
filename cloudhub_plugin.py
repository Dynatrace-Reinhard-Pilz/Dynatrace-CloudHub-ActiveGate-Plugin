import json
import requests
import time
from ruxit.api.base_plugin import RemoteBasePlugin
import logging
import uuid
import socket

logger = logging.getLogger(__name__)

URL_APPLICATONS = "https://anypoint.mulesoft.com/cloudhub/api/applications"
URL_ACCOUNT = "https://anypoint.mulesoft.com/accounts/api/me"
URL_TPL_DASHBOARD_STATS = "https://anypoint.mulesoft.com/cloudhub/api/v2/applications/{domain}/dashboardStats?domain={domain}&interval=7200000"
URL_TPL_WORKERS = "https://anypoint.mulesoft.com/cloudhub/api/applications/{domain}/workers"
URL_REGIONS = "https://anypoint.mulesoft.com/cloudhub/api/regions"
URL_TPL_ENVIRONMENTS = "https://anypoint.mulesoft.com/accounts/api/organizations/{organizationId}/environments"
URL_TPL_STATISTICS = "https://anypoint.mulesoft.com/cloudhub/api/applications/{domain}/statistics?period=60000&intervalCount=1"

class CloudHubPlugin(RemoteBasePlugin):

    def initialize(self, **kwargs):
        config = kwargs['config']
        json_config = kwargs["json_config"]
        self.timeSeries = {}
        for metric in json_config["metrics"]:
            self.timeSeries[metric["timeseries"]["key"]] = metric["timeseries"]

    def query(self, **kwargs):
        config = kwargs["config"]
        user = config["user"]
        password = config["pass"]
        env_id = None
        
        session = requests.Session()
        session.auth  = (user, password)
        
        regions = {}
        regions_array = json.loads(session.get(URL_REGIONS, headers = {}).content.decode())
        for region in regions_array:
            regions[region["id"]] = region["name"]
        
        account = json.loads(session.get(URL_ACCOUNT, headers = {}).content.decode())
        
        organization_id = account["user"]["organizationId"]
        organization_name = account["user"]["organization"]["name"]
        
        url_environments = URL_TPL_ENVIRONMENTS.replace("{organizationId}", organization_id)
        environments = json.loads(session.get(url_environments, headers = {}).content.decode())["data"]
        for environment in environments:
            environment_id = environment["id"]
            environment_name = environment["name"]
            
            group = self.topology_builder.create_group(environment_id, environment_name)
            group.report_property("MuleSoft Organization", organization_name)
            group.report_property("MuleSoft OrganizationId", organization_id)
            if "type" in environment:
                group.report_property("MuleSoft Environment Type", environment["type"])
            if "isProduction" in environment:
                if environment["isProduction"]:
                    group.report_property("MuleSoft Production Environment", "True")
                else:
                    group.report_property("MuleSoft Production Environment", "False")
            
            headers = { "X-ANYPNT-ENV-ID": environment_id }
            
            applications = json.loads(session.get(URL_APPLICATONS, headers = headers).content.decode())
            for application in applications:
                application_domain = application["domain"]
                application_id = application["id"]
                application_full_domain = application["fullDomain"]
                application_ip = socket.gethostbyname(application_full_domain)
                if application_ip.startswith("/"):
                    application_ip = application_ip[1:]                
                num_workers = application["workers"]
                num_started_workers = 0
                
                node = group.create_element(application_id, application_domain)
                node.report_property("MuleSoft Domain", application_full_domain)
                if 'region' in application:
                    node.report_property("AWS Region", regions[application["region"]])
                if 'fileName' in application:
                    node.report_property("File Name", application["fileName"])
                if 'filename' in application:
                    node.report_property("File Name", application["filename"])
                if 'href' in application:
                    node.report_property("HRef", application["href"])
                if 'workerType' in application:
                    node.report_property("Worker Type", application["workerType"])
                if 'muleVersion' in application:
                    node.report_property("Mule Version", application["muleVersion"])
                if 'instanceSize' in application:
                    node.report_property("Instance Size", application["instanceSize"])
                if 'staticIPsEnabled' in application:
                    if application["staticIPsEnabled"]:
                        node.report_property("Static IPs", "True")
                    else:
                        node.report_property("Static IPs", "False")
                if 'persistentQueues' in application:
                    if application["persistentQueues"]:
                        node.report_property("Persistent Queues", "True")
                    else:
                        node.report_property("Persistent Queues", "False")
                if 'muleVersion' in application:
                    application_mule_version = application["muleVersion"]
                    if 'version' in application_mule_version:
                        group.report_property("Mule Version", application_mule_version["version"])
                url_workers = URL_TPL_WORKERS.replace("{domain}", application_domain)
                workers = json.loads(session.get(url_workers, headers = headers).content.decode())
                worker_map = {}
                for worker in workers:
                    worker_map[worker["id"]] = worker
                url_dashboard_stats = URL_TPL_DASHBOARD_STATS.replace("{domain}", application_domain)
                dashboard_stats = json.loads(session.get(url_dashboard_stats, headers = headers).content.decode())
                worker_statistics = dashboard_stats["workerStatistics"]
                for worker_stats in worker_statistics:
                    worker_id = worker_stats["id"]
                    worker_ip_address = worker_stats["ipAddress"]
                    worker_port = worker_map[worker_id]["port"]
                    if worker_map[worker_id]["status"] == "STARTED":
                        num_started_workers = num_started_workers + 1
                    
                    statistics = worker_stats["statistics"]
                    node.add_endpoint(application_ip, worker_port, dnsNames = [ application_full_domain ])
                    for metric, measurements in statistics.items():
                        if metric not in self.timeSeries:
                            continue
                        timestamp = 0
                        latest_measurement = 0.0
                        if type(measurements) is dict:
                            for s_timestamp, measurement in measurements.items():
                                parsed_timstamp = int(s_timestamp)
                                if parsed_timstamp > timestamp:
                                    timestamp = parsed_timstamp
                                    latest_measurement = measurement
                        elif type(measurements) is float:
                            timestamp = int(time.time())
                            latest_measurement = measurements
                        if timestamp > 0:
                            node.absolute(key=metric, value=latest_measurement, dimensions = { "worker" : worker_id } )
                node.absolute(key="totalWorkers", value=num_workers)
                node.absolute(key="startedWorkers", value=num_started_workers)
                node.absolute(key="stoppedWorkers", value=(num_workers - num_started_workers))
                url_statistics = URL_TPL_STATISTICS.replace("{domain}", application_domain)
                application_statistics = json.loads(session.get(url_statistics, headers = headers).content.decode())
                for ts, num_requests in application_statistics.items():
                    node.absolute(key="rpm", value=num_requests)