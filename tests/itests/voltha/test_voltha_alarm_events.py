from unittest import main
from common.utils.consulhelpers import get_endpoint_from_consul
from tests.itests.docutests.test_utils import \
    run_long_running_command_with_timeout
from tests.itests.voltha.rest_base import RestBase
from google.protobuf.json_format import MessageToDict
from voltha.protos.device_pb2 import Device
import simplejson, jsonschema
import re

# ~~~~~~~ Common variables ~~~~~~~

LOCAL_CONSUL = "localhost:8500"

COMMANDS = dict(
    kafka_client_run="kafkacat -b {} -L",
    kafka_client_alarm_check="kafkacat -o -5 -b {} -C -t voltha.alarms -c 10",
)

ALARM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "type": {"type": "string"},
        "category": {"type": "string"},
        "state": {"type": "string"},
        "severity": {"type": "string"},
        "resource_id": {"type": "string"},
        "raised_ts": {"type": "number"},
        "reported_ts": {"type": "number"},
        "changed_ts": {"type": "number"},
        "description": {"type": "string"},
        "context": {
            "type": "object",
            "additionalProperties": {"type": "string"}
        }
    }
}


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


class VolthaAlarmEventTests(RestBase):
    # Retrieve details on the REST entry point
    rest_endpoint = get_endpoint_from_consul(LOCAL_CONSUL, 'chameleon-rest')

    # Construct the base_url
    base_url = 'http://' + rest_endpoint

    # Start by querying consul to get the endpoint details
    kafka_endpoint = get_endpoint_from_consul(LOCAL_CONSUL, 'kafka')

    # ~~~~~~~~~~~~ Tests ~~~~~~~~~~~~

    def test_alarm_topic_exists(self):
        # We want to make sure that the topic is available on the system
        expected_pattern = ['voltha.alarms']

        # Start the kafka client to retrieve details on topics
        cmd = COMMANDS['kafka_client_run'].format(self.kafka_endpoint)
        kafka_client_output = run_long_running_command_with_timeout(cmd, 20)

        # Loop through the kafka client output to find the topic
        found = False
        for out in kafka_client_output:
            if all(ep in out for ep in expected_pattern):
                found = True
                break

        self.assertTrue(found,
                        'Failed to find topic {}'.format(expected_pattern))

    def test_alarm_generated_by_adapter(self):
        # Verify that REST calls can be made
        self.verify_rest()

        # Create a new device
        device = self.add_device()

        # Activate the new device
        self.activate_device(device['id'])

        # The simulated olt device should start generating alarms periodically
        alarm = self.get_alarm_event(device['id'])

        # Make sure that the schema is valid
        self.validate_alarm_event_schema(alarm)

        # Validate the constructed alarm id
        self.verify_alarm_event_id(device['id'], alarm['id'])

    # ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    # Make sure the Voltha REST interface is available
    def verify_rest(self):
        self.get('/api/v1')

    # Create a new simulated device
    def add_device(self):
        device = Device(
            type='simulated_olt',
        )
        device = self.post('/api/v1/local/devices', MessageToDict(device),
                           expected_code=200)
        return device

    # Active the simulated device.
    # This will trigger the simulation of random alarms
    def activate_device(self, device_id):
        path = '/api/v1/local/devices/{}'.format(device_id)
        self.post(path + '/activate', expected_code=200)
        device = self.get(path)
        self.assertEqual(device['admin_state'], 'ENABLED')

    # Retrieve a sample alarm for a specific device
    def get_alarm_event(self, device_id):
        cmd = COMMANDS['kafka_client_alarm_check'].format(self.kafka_endpoint)
        kafka_client_output = run_long_running_command_with_timeout(cmd, 20)

        # Verify the kafka client output
        found = False
        self.alarm_data = None

        for out in kafka_client_output:
            self.alarm_data = simplejson.loads(out)

            print self.alarm_data

            if 'resource_id' not in self.alarm_data:
                continue
            elif self.alarm_data['resource_id'] == device_id:
                found = True
                break

        self.assertTrue(
            found,
            'Failed to find kafka alarm with device id:{}'.format(device_id))

        return self.alarm_data

    # Verify that the alarm follows the proper schema structure
    def validate_alarm_event_schema(self, alarm):
        try:
            jsonschema.validate(alarm, ALARM_SCHEMA)
        except Exception as e:
            self.assertTrue(
                False, 'Validation failed for alarm : {}'.format(e.message))

    # Verify that alarm identifier based on the format generated by default.
    def verify_alarm_event_id(self, device_id, alarm_id):
        prefix = re.findall(r"(voltha)\.(\w+)\.(\w+)", alarm_id)

        self.assertEqual(
            len(prefix), 1,
            'Failed to parse the alarm id: {}'.format(alarm_id))
        self.assertEqual(
            len(prefix[0]), 3,
            'Expected id format: voltha.<adapter name>.<device id>')
        self.assertEqual(
            prefix[0][0], 'voltha',
            'Expected id format: voltha.<adapter name>.<device id>')
        self.assertEqual(
            prefix[0][1], 'simulated_olt',
            'Expected id format: voltha.<adapter name>.<device id>')
        self.assertEqual(
            prefix[0][2], device_id,
            'Expected id format: voltha.<adapter name>.<device id>')


if __name__ == '__main__':
    main()
