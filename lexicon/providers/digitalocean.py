from __future__ import absolute_import

import json
import logging

import requests

from lexicon.providers.base import Provider as BaseProvider

LOGGER = logging.getLogger(__name__)

NAMESERVER_DOMAINS = ['digitalocean.com']


def ProviderParser(subparser):
    subparser.add_argument(
        "--auth-token", help="specify token for authentication")


class Provider(BaseProvider):

    def __init__(self, config):
        super(Provider, self).__init__(config)
        self.domain_id = None
        self.api_endpoint = 'https://api.digitalocean.com/v2'

    def authenticate(self):

        payload = self._get('/domains/{0}'.format(self.domain))
        self.domain_id = self.domain

    def create_record(self, type, name, content):
        # check if record already exists
        if len(self.list_records(type, name, content)) == 0:
            record = {
                'type': type,
                'name': self._relative_name(name),
                'data': content,

            }
            if type == 'CNAME':
                # make sure a the data is always a FQDN for CNAMe.
                record['data'] = record['data'].rstrip('.') + '.'

            payload = self._post(
                '/domains/{0}/records'.format(self.domain_id), record)
        LOGGER.debug('create_record: %s', True)
        return True

    # List all records. Return an empty list if no records found
    # type, name and content are used to filter records.
    # If possible filter during the query, otherwise filter after response is received.
    def list_records(self, type=None, name=None, content=None):
        url = '/domains/{0}/records'.format(self.domain_id)
        records = []
        payload = {}

        next = url
        while next is not None:
            payload = self._get(next)
            if 'links' in payload \
                    and 'pages' in payload['links'] \
                    and 'next' in payload['links']['pages']:
                next = payload['links']['pages']['next']
            else:
                next = None

            for record in payload['domain_records']:
                processed_record = {
                    'type': record['type'],
                    'name': "{0}.{1}".format(record['name'], self.domain_id),
                    'ttl': '',
                    'content': record['data'],
                    'id': record['id']
                }
                records.append(processed_record)

        if type:
            records = [record for record in records if record['type'] == type]
        if name:
            records = [record for record in records if record['name']
                       == self._full_name(name)]
        if content:
            records = [
                record for record in records if record['content'].lower() == content.lower()]

        LOGGER.debug('list_records: %s', records)
        return records

    # Create or update a record.
    def update_record(self, identifier, type=None, name=None, content=None):

        data = {}
        if type:
            data['type'] = type
        if name:
            data['name'] = self._relative_name(name)
        if content:
            data['data'] = content

        payload = self._put(
            '/domains/{0}/records/{1}'.format(self.domain_id, identifier), data)

        LOGGER.debug('update_record: %s', True)
        return True

    # Delete an existing record.
    # If record does not exist, do nothing.
    def delete_record(self, identifier=None, type=None, name=None, content=None):
        delete_record_id = []
        if not identifier:
            records = self.list_records(type, name, content)
            delete_record_id = [record['id'] for record in records]
        else:
            delete_record_id.append(identifier)

        LOGGER.debug('delete_records: %s', delete_record_id)

        for record_id in delete_record_id:
            payload = self._delete(
                '/domains/{0}/records/{1}'.format(self.domain_id, record_id))

        # is always True at this point, if a non 200 response is returned an error is raised.
        LOGGER.debug('delete_record: %s', True)
        return True

    # Helpers

    def _request(self, action='GET',  url='/', data=None, query_params=None):
        if data is None:
            data = {}
        if query_params is None:
            query_params = {}
        default_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {0}'.format(self._get_provider_option('auth_token'))
        }
        if not url.startswith(self.api_endpoint):
            url = self.api_endpoint + url

        r = requests.request(action, url, params=query_params,
                             data=json.dumps(data),
                             headers=default_headers)
        # if the request fails for any reason, throw an error.
        r.raise_for_status()
        if action == 'DELETE':
            return ''
        else:
            return r.json()
