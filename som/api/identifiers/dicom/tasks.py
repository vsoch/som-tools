'''
tasks.py: functions to extract identifiers from dicom images

Copyright (c) 2017 Vanessa Sochat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


import importlib
from som.logger import bot
from som.utils import (
    read_json
)

from som.api.identifiers.standards import (
    valid_actions
)

from som.api.identifiers.utils import (
    create_lookup
)


from pydicom import read_file
from pydicom.errors import InvalidDicomError
import dateutil.parser
import tempfile

here = os.path.dirname(os.path.abspath(__file__))

######################################################################
# HELPERS
######################################################################

def get_func(function_name):
    '''get_func will return a function that is defined from a string.
    the function is assumed to be in this file
    '''
    env = globals()
    if function_name in env:
        return env[function_name]
    return None


def perform_action(dicom,response,params):
    '''perform action takes  
    :param dicom: a loaded dicom file (pydicom read_file)
    and a dictionary of params.
    :param response: the api response, with "id", "id_source" "items"
    at the top level
    :param params:
        "name" (eg, PatientID) the header field to process
        "action" (eg, coded) what to do with the field
        "value": if needed, the field from the response to replace with
    '''
    if default_action is None:
        default_action = "blanked"

    header = entity_action.get('name')   # e.g: PatientID
    action = entity_action.get('action') # "coded"
    value = entity_action.get('value')   # "suid"
    done = False

    if header in dicom:

        # Blank the value
        if action == "blank":
            dicom.update({header:""})
            done = True
 
        # Code the value with something in the response
        elif entity_action == "coded":
            if value in response:
                dicom.update({header:response[value]})
                done = True

        # Remove the field entirely
        elif entity_action == "remove":
            done = True
            del dicom[header]

        # Do nothing. Keep the original
        elif entity_action == "original":
            done = True

        if not done:            
            dicom.update({header:""})

    return dicom


######################################################################
# CONFIG DEFINED FUNCS
######################################################################

def get_item_timestamp(dicom):
    '''get_item_timestamp will return the UTC time for an instance.
    This is derived from the InstanceCreationDate and InstanceCreationTime
    If the Time is not set, only the date is used.
    # testing function https://gist.github.com/vsoch/23d6b313bd231cad855877dc544c98ed
    '''
    item_time = dicom.get("InstanceCreationTime","")
    item_date = dicom.get("InstanceCreationDate")
    timestamp = dateutil.parser.parse("%s%s" %(item_date,item_time))
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_entity_timestamp(dicom):
    '''get_entity_timestamp will return a UTC timestamp for the entity,
    derived from the patient's birthdate. In the config.json, this is
    set by setting type=func, and value=get_entity_timestamp
    '''
    item_date = dicom.get("PatientBirthDate")
    timestamp = dateutil.parser.parse("%s" %(item_date))
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


######################################################################
# MAIN GET FUNCTIONS
######################################################################

def get_identifier(tag,dicom,template):
    '''get_id will use a template and an image to return the user's
    preference for some identifier
    :param tag: the name of the identifier (eg, id, id_source)
    :param dicom: the dicom image, already read in
    :param template: the config['item']/config['entity'] template
    '''
    result = None
    if tag in template:
        action = template[tag]['type']
        value = template[tag]['value']

        # Extracted from data
        if action == "data":
            if isinstance(value,list):
                result = [{"key":x,"value":dicom.get(x)} for x in value if dicom.get(x) not in [None,""]]
            else:
                result = dicom.get(value)

        # Custom function in this file that takes dicom image
        elif action == "func":
            func = get_func(value)
            result = func(dicom)

        elif action == "default":
            result = value

        # Retrieve from environment
        elif action == "env":
            if isinstance(value,list):
                result = [os.environ.get(x) for x in value if 
                          os.environ.get(x) is not None]
            else:
                result = os.environ.get(value)

    if result == "":
        result = None
    return result


def get_identifiers(dicom_files,force=True,config=None):
    '''extract and validate identifiers from a dicom image that conform
    to the expected request to the identifiers api. This function cannot be
    sure if more than one source_id is present in the data, so it returns
    a lookup dictionary by patient id.
    :param dicom_files: the dicom file(s) to extract from
    :param force: force reading the file (default True)
    :param config: if None, uses default in provided module folder
    '''

    if config is None:
        config = "%s/config.json" %(here)

    if not os.path.exists(config):
        bot.error("Cannot find config %s, exiting" %(config))

    # get_identifiers needs to know about request
    config = read_json(config)['request'] 

    if not isinstance(dicom_files,list):
        dicom_files = [dicom_files]

    ids = dict() # identifiers

    for dicom_file in dicom_files:

        dicom = read_file(dicom_file,force=True)

        # Read in / calculate preferred values
        entity_id = get_identifier(tag='id',
                                   dicom=dicom,
                                   template=config['entity'])
        bot.debug('entity id: %s' %(entity_id))

        source_id = get_identifier(tag='id_source',
                                   dicom=dicom,
                                   template=config['entity'])
        bot.debug('entity source_id: %s' %(source_id))

        item_id = get_identifier('id',
                                 dicom=dicom,
                                 template=config['item'])
        bot.debug('item id: %s' %(item_id))


        entity_fields = get_identifier('custom_fields',
                                      dicom=dicom,
                                      template=config['entity'])
        bot.debug('entity custom_fields: %s' %(entity_fields))


        item_source = get_identifier('id_source',
                                     dicom=dicom,
                                     template=config['item'])
        bot.debug('item source: %s' %(item_source))


        item_fields = get_identifer('custom_fields',
                                     dicom=dicom,
                                     template=config['item'])
        bot.debug('item custom_fields: %s' %(item_fields))

        # Skip images without patient id or item id
        if entity_id is not None and item_id is not None:

           # Only need to add the entity once
           if entity_id not in ids:
               ids[entity_id] = {'identifiers': { 'id': entity_id } } 
               ids[entity_id]['items'] = []
               ids[entity_id]['identifiers']['custom_fields'] = custom_fields


           # Item is always added
           item = dict()
           item['custom_fields'] = item_fields
           item['id_source'] = item_source
           ids[entity_id]['items'].append(item) 

        else:
            bot.warning("Skipping %s due to empty entity (%s) or item (%s) id" %(dicom_file,entity_id,item_id))
    return ids



def replace_identifiers(response,dicom_files,force=True,config=None,overwrite=True):
    '''replace identifiers will replace dicom_files with a response
    from the identifiers API. 
    :param response: the response from the API, or a list of identifiers
    :param dicom_files: the dicom file(s) to extract from
    :param force: force reading the file (default True)
    :param config: if None, uses default in provided module folder
    :param overwrite: if False, save updated files to temporary directory
    '''
    if overwrite is False:
        save_base = tempfile.mkdtemp()

    if config is None:
        config = "%s/config.json" %(here)

    if not os.path.exists(config):
        bot.error("Cannot find config %s, exiting" %(config))

    config = read_json(config)

    if not isinstance(dicom_files,list):
        dicom_files = [dicom_files]

    # We should have a list of responses
    lookup = create_lookup(response)

    ## Actions/Additions for each come from config
    additions = config['response']['additions']

    # Does the config want additions?
    has_additions = False
    if len(additions) > 0:
        has_additions = True
        for addition in additions:
            bot.debug("%s will be added as %s to all datasets." %(addition['name'],
                                                                  addition['value']))

    # Get specified actions
    item_actions = config['response']['item']['actions']
    entity_actions = config['response']['entity']['actions']
    
    # Parse through dicom files, update headers, and save
    updated_files = []

    for dicom_file in dicom_files:

        dicom = read_file(dicom_file,force=True)

        # Read in / calculate preferred values
        entity_id = get_identifier(tag='id',
                                   dicom=dicom,
                                   template=config['request']['entity'])

        item_id = get_identifier(tag='id',
                                 dicom=dicom,
                                 template=config['request']['item'])


        # Is the entity_id in the data structure given to de-identify?
        if entity_id in lookup:
            result = lookup[entity_id]

            fields = dicom.dir()
            
            # Returns same dicom with action performed
            for entity_action in entity_actions:

                # We've dealt with this field
                fields = [x for x in fields if x != entity_action['name']]
                dicom = perform_action(dicom=dicom,
                                       response=result
                                       params=entity_action)

            if "items" in result:

                for item in result['items']:

                    # Is this API response for this dicom?
                    if item['id'] == item_id
                        for item_action in item_actions:

                           # Returns same dicom with action performed
                           fields = [x for x in fields if x != item_action['name']]
                           dicom = perform_action(dicom=dicom,
                                                  response=item
                                                  params=item_action)


            # Blank remaining fields
            for field in fields:
                dicom.update({field:""})

            # Save to file
            output_dicom = dicom_file
            if overwrite is False:
                output_dicom = "%s/%s" %(save_base,os.path.basename(dicom_file))
            dicom.save_as(output_dicom)

            update_files.append(output_dicom)
       
        else:
            bot.warning("%s not found in identifiers lookup. Skipping" %(entity_id))

    return updated_files