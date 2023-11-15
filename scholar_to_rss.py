#!/bin/env python3
# -*- coding: utf-8 -*-
import os
import time
import json
import requests
import configparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import msal

class Scholar2RSS:

    def __init__(self, APP_ID):
        self.APP_ID = APP_ID
        self.GRAPH_ENDPOINT = 'https://graph.microsoft.com/v1.0'
        self.SCOPES = ['Mail.ReadWrite']
        self.MS_API_TOKEN = './ms_graph_api_token.json'
        self.XML_PATH = './scholar.xml'

    def convert_to_timestamp(self, date_string):
        date_obj = datetime.strptime(date_string, "%a, %d %b %Y %H:%M:%S %z")
        return date_obj.timestamp()

    def generate_access_token(self):
        # Save Session Token as a token file
        access_token_cache = msal.SerializableTokenCache()

        # read the token file
        if os.path.exists(self.MS_API_TOKEN):
            access_token_cache.deserialize(open(self.MS_API_TOKEN, "r").read())
            token_detail = json.load(open(self.MS_API_TOKEN,))
            token_detail_key = list(token_detail['AccessToken'].keys())[0]
            token_expiration = datetime.fromtimestamp(int(token_detail['AccessToken'][token_detail_key]['expires_on']))
            # if datetime.now() > token_expiration:
            #     os.remove(self.MS_API_TOKEN)
            #     access_token_cache = msal.SerializableTokenCache()

        # assign a SerializableTokenCache object to the client instance
        client = msal.PublicClientApplication(client_id=self.APP_ID, token_cache=access_token_cache)

        accounts = client.get_accounts()
        if accounts:
            # load the session
            token_response = client.acquire_token_silent(self.SCOPES, accounts[0])
        else:
            # authetnicate your accoutn as usual
            flow = client.initiate_device_flow(scopes=self.SCOPES)
            print('Open https://microsoft.com/devicelogin, user_code: ' + flow['user_code'])
            token_response = client.acquire_token_by_device_flow(flow)

        with open(self.MS_API_TOKEN, 'w') as _f:
            _f.write(access_token_cache.serialize())

        return token_response

    def get_mail(self):
        endpoint = self.GRAPH_ENDPOINT + '/me/messages'
        access_token = self.generate_access_token()
        headers = {'Authorization': 'Bearer ' + access_token['access_token']}
        request_body = {
            '$select': 'sender, subject, body',
            'filter': 'isRead eq false and from/emailAddress/address eq \'scholaralerts-noreply@google.com\''
        }

        response = requests.get(endpoint, headers=headers, params=request_body)
        if response.status_code == 200:
            content = json.loads(response.text)
            if content['value']:
                return content['value']
            else:
                print('No new mail.')
                return None
        else:
            print(response.text)
            return None
        
    def mark_mail_as_read(self, id):
        access_token = self.generate_access_token()
        headers = {
            'Authorization': 'Bearer ' + access_token['access_token'],
            'Content-Type': 'application/json',
        }
        request_body = {'isRead': True}

        endpoint = self.GRAPH_ENDPOINT + '/me/messages/' + id
        response = requests.patch(endpoint, headers=headers, data=json.dumps(request_body))
        if response.status_code != 200:
            print(response.text)

    def update_xml_file(self, mail):
        # Create xml file
        if not os.path.exists(self.XML_PATH):
            content = '<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0"><channel>'\
                    + '<title><![CDATA[' + "Google Scholar Alert" + ']]></title>' \
                    + '<link>' + 'https://scholar.google.com/' + '</link>'\
                    + '<description><![CDATA[' + "Google Scholar" + ']]></description>' \
                    + '<language>zh-cn</language>' \
                    + '</channel></rss>'
            with open(self.XML_PATH, 'w') as file:
                file.write(content)

        # Read xml file
        xmlContent = ''
        with open(self.XML_PATH, 'r') as file:
            xmlContent = file.read()
        xmlContent = BeautifulSoup(xmlContent.replace('link>','temptlink>'),'lxml')

        # parse mail content
        mail_title = mail['subject']

        mail_content = BeautifulSoup(mail["body"]["content"], 'html.parser')
        links, titles, authors, abstracts = [], [], [], []
        subjects = mail_content.find_all('a', class_=lambda value: value and 'alrt_title' in value)
        for subject in subjects:
            links.append(subject.get('href'))
            titles.append(subject.get_text(strip=True))
        subjects = mail_content.select('div[style*="color:#006621"]')
        for subject in subjects:
            authors.append(subject.get_text(strip=True))
        subjects = mail_content.find_all('div', class_=lambda value: value and 'alrt_sni' in value)
        for subject in subjects:
            abstracts.append(subject.get_text(strip=True))

        # Concreate new content
        for index, link in enumerate(links):
            elementContent = '<title><![CDATA[' + mail_title + '. ' + titles[index] + ']]></title>' \
                            + '<description><![CDATA[' + "<p><b>" + authors[index] + "</b></p>" \
                            + "<p>" + "<b>Abstract:</b>" + abstracts[index] + "</p>" + ']]></description>'\
                            + '<temptlink>' + links[index] + '</temptlink>'\
                            + '<pubDate>' + time.strftime("%a, %d %b %Y %H:%M:%S %z", time.localtime(int(time.time()))) + '</pubDate>'
            
            parent = xmlContent.select_one('channel')
            new_item = xmlContent.new_tag('item')
            new_item.string = elementContent
            parent.append(new_item)
                            
        xmlContent = BeautifulSoup(str(xmlContent.body.contents[0]).replace('&amp;','&').replace('&lt;','<').replace('&gt;','>'),'lxml')
        items = xmlContent.find_all('item')
        # sort <item> by pubDate
        sorted_items = sorted(items, key=lambda x: self.convert_to_timestamp(x.select_one('pubDate').text), reverse=True)

        # remove <item> older than 2 weeks if there are more than 100 <item>
        if len(sorted_items) > 100:
            # get timestamp of 2 weeks ago
            two_week_ago = datetime.now() - timedelta(days=14)
            two_week_ago_timestamp = time.mktime(two_week_ago.timetuple())
            for item in sorted_items.copy():
                pub_date = item.select_one('pubDate').text
                pub_date_timestamp = self.convert_to_timestamp(pub_date)
                if pub_date_timestamp < two_week_ago_timestamp:
                    sorted_items.remove(item)

        # remove all <item> in xmlContent
        items_in_xmlContent = xmlContent.find_all('item')
        for item in items_in_xmlContent:
            item.extract()
        
        # append sorted <item> to xmlContent
        parent_element = xmlContent.find('channel')
        for sorted_item in sorted_items:
            parent_element.append(sorted_item)

        with open(self.XML_PATH, 'w') as f:
            f.write(str(xmlContent.body.contents[0]).replace('&lt;','<').replace('&gt;','>').replace('temptlink','link'))
        
if __name__ == '__main__':

    config = configparser.ConfigParser()
    config.read('./config.ini')
    APP_ID = config.get('Config', 'APP_ID')

    scholar2rss = Scholar2RSS(APP_ID)

    mails = scholar2rss.get_mail()

    # Extract content from mails
    if mails:
        for mail in mails:
            scholar2rss.update_xml_file(mail)
    else:
        exit()

    # mark mail as read
    for mail in mails:
        scholar2rss.mark_mail_as_read(mail['id'])