from flask import Flask, request, render_template, jsonify, send_file, send_from_directory
from pytube import YouTube
from pytube import Channel
from other_functions import UDF_func as udf, UDF_connections as con, oops_file as oops
import boto3
from botocore.exceptions import NoCredentialsError
import os
import urllib.request
from werkzeug.utils import secure_filename
import pandas as pd
import zipfile
import logging


global logger

app = Flask(__name__)

# Create and configure logger
logging.basicConfig(filename="newfile.log",
                    format='%(asctime)s %(message)s',
                    filemode='w')
# Creating an object
global logger
logger = logging.getLogger()

# Setting the threshold of logger to DEBUG
logger.setLevel(logging.DEBUG)

@app.route('/', methods=['GET'])
def homepage():
    return render_template("index.html")


@app.route('/scrap_new_request', methods=['GET'])
def new_scrap_request():
    # Documenting new request Will help to read log
    logger.debug("-----------route -scrap_new_request---------------------")

    # Clint input
    channel_url = request.args.get('channel_name')
    vdo_limit = int(request.args.get('target_nunOf_vdos'))
    target_vdo_len = int(request.args.get('target_length'))
    logger.debug("Client Info -- Channel Name = %s, vdo limit = %s, vdo len limit= %s" %(channel_url, vdo_limit, target_vdo_len))

    # trying to fetch vdo urls of the channel
    #Step--1
    try:
        channel_url = Channel(channel_url)  # pytube processing
    except Exception as e:
        logger.error('step-1 Error:-- %s' % (str(e)))
        return {
            'status': -1,
            'errorMassage': 'Error: could not fetch the channel info from channel url <br> Key error: %s' %(str(e))
        }
    else:
        logger.debug("'step-1 Success:--- pytube channel info extracted")

    # list for hold data for all the videos
    sql_upload_list = []
    mongo_upload_list = []
    mongo_upload_dict = {'channel_name': channel_url.channel_name,
                         'list_of_vdos': {}}

    # Step-2(S2) -------------- for each vdo in the vdo list of chanl
    counter = 0
    for vdo_url in channel_url.video_urls:
        yt = YouTube(vdo_url)

        # checking the length of the vdo from pytube api -- return in sec
        vdo_len = yt.length / 60

        # considering videos with user given target length
        if vdo_len < target_vdo_len:
            # creating new Object
            try:
                new_vdo = oops.vedio(vdo_url, vdo_len)
            except Exception as e:
                logger.error('Step-2.1 Error for creating OBJECT with URL %s:---- %s' % (vdo_url, str(e)) )
                return {
                    'status': -1,
                    'errorMassage': f'Error occurred while creating object for video url - {vdo_url}  , Error key: {str(e)}  '
                }

            # calling object function -- create a dict with all info that will be loaded in mysql
            try: # Step 2.2
                sql_upload_list.append(new_vdo.create_sqlLoad_dict())
            except Exception as e:
                logger.error('Step-2.2 Error for creating SQL data dict with URL %s:---- %s' % (vdo_url, str(e)) )
                return {
                    'status': -1,
                    'errorMassage': f'Error occurred while creating sql data dict for video url - {vdo_url}, Error key: {str(e)}  '
                }


            # calling object function -- create a dict with all info that will be loaded in mongodb
            try:
                mongo_upload_list.append(new_vdo.create_comment_info_dict())
                x = mongo_upload_dict['list_of_vdos']
                x.update(new_vdo.create_comment_info_dict())
            except Exception as e:
                logger.error('Step-2.3 Error for creating mongoDB comment dict with URL %s:---- %s' % (vdo_url, str(e)) )
                return {
                    'status': -1,
                    'errorMassage': f'Error occurred while creating mondo comment dict for video url - {vdo_url}, <br> Error key: {str(e)}  '
                }

            counter = counter + 1

        if counter > vdo_limit - 1:
            break  # if the limit is reached

    # creating df from all the vdo info
    df = pd.DataFrame(sql_upload_list)


    # Uploading info to mysql --- Step-3
    try:
        engine = con.create_sql_engine()
        df.to_sql('basic_scrap_info', engine, if_exists='append', index=False)
        engine.dispose()
    except Exception as e:
        logger.error('Step-3 Error for uploading data in mySQL,| Msg: %s' % (str(e)))
        return {
            'status': -1,
            'errorMassage': f'Error occurred while uploading data in mySQL, <br> Error key: {str(e)}  '
        }
    else:
        logger.debug('Step 3 completed... Data loaded to mySQL')

    # uploading to mongoDb ----- Step 4
    try:
        client = con.create_mongodb_conn()
        db = client['mongotest']
        collection = db['testLoadtest5']
        # collection.insert_one({channel_url.channel_name: mongo_upload_list})
        collection.insert_one(mongo_upload_dict)

    except Exception as e:
        logger.error('Step-4 Error for uploading data in mongoDb,| Msg: %s' % (str(e)))
        return {
            'status': -1,
            'errorMassage': f'Error occurred while uploading data in mongoDb, <br> Error key: {str(e)}  '
        }
    else:
        logger.debug('Step 4 completed... Data loaded to mySQL')
        logger.debug('.............................Route Completed Successfully ........scrapNewReq.......................')
    return 'Data is loaded successfully'


@app.route('/fetch_dataFromDb', methods=['GET'])
def fetchDataFromDb():
    logger.debug("-----------route -fetch data from db---------------------")
    channel_url = request.args.get('channel_name')

    try:  # trying to fetch vdo urls of the channel
        channel = Channel(channel_url)  # pytube processing
        chnnl_id = channel.channel_id
        chnnl_name = channel.channel_name
    except Exception as e:
        logger.error("Ste1-- ERROR - Could not collect the channel info. Error-key: %s" %(str(e)) )
        return {
            'status': -1,
            'errorMassage': "ERROR - Could not collect the channel info. Make sure the channel url is valid <br> Error-key: %s" %(str(e))
        }
    else:
        logger.error("Ste1-- Completed here")

    try:  # Step 2
        basicInfo_table_text = udf.fetch_scrapped_info_frmMysql(chnnl_id)
    except Exception as e:
        logger.error("Ste2-- ERROR - unable to receive muSQL data. Error-key: %s" % (str(e)))
        return {
            'status': -1,
            'errorMassage': "ERROR - Could not collect data from mySql. <br> Error-key: %s" % (str(e))
        }
    else:
        logger.error("Ste2-- Completed here")

    try:   #step--3
        comment_table_text = udf.fetch_scrapped_info_frmMongoDb(chnnl_name)
    except Exception as e:
        logger.error("Ste2-- ERROR - unable to receive mongoDb data. Error-key: %s" % (str(e)))
        return {
            'status': -1,
            'errorMassage': "ERROR - Could not collect comment info from mongoDb. <br> Error-key: %s" % (str(e))
        }
    else:
        logger.error("Ste3-- Completed here")

    return jsonify({'basic_info': basicInfo_table_text,
                    'comment_info': comment_table_text})


@app.route('/download_videos', methods=['GET'])
def download_vdos():

    channel_url = request.args.get('channel_name')

    try:  # trying to fetch vdo urls of the channel
        channel_url = Channel(channel_url)  # pytube processing
    except:
        return "ERROR - Could not collect the channel info. Make sure the channel url is valid "

    # fetching all videos
    all_video = channel_url.videos
    print(all_video)
    # no of videos  user wants fetch the data of
    vdo_limit = int(request.args.get('target_nunOf_vdos'))
    target_vdo_len = int(request.args.get('target_length'))

    counter = 0
    for vdo in all_video:

        vdo.streams.first().download(output_path='/static/vdo_download')
        counter = counter + 1
        if counter > 1:
            break  # if the limit is reached


    # Zip file Initialization
    # zipfolder = zipfile.ZipFile('Audiofiles.zip', 'w', compression=zipfile.ZIP_STORED)  # Compression type
    #
    # # zip all the files which are inside in the folder
    # for root, dirs, files in os.walk('<foldername>'):
    #     for file in files:
    #         zipfolder.write('/static/vdo_download' + file)
    # zipfolder.close()
    #
    # return send_file('Audiofiles.zip',
    #                  mimetype='zip',
    #                  attachment_filename='Audiofiles.zip',
    #                  as_attachment=True)
    #
    # # Delete the zip file if not needed
    # os.remove("Audiofiles.zip")

    return 'Download successful'


@app.route('/upload_vdo_toS3', methods=['POST'])
def upload_VDO_ToS3():
    # -----------------------------------------------------
    # Connectint to s3
    s3 = boto3.client('s3', region_name='us-west-2')
    bucket_name = 'yt-vdo-uploaded'
    # local_file = 'C:/Users/koust/Documents/vdo1.3gpp'
    s3_file_name = 'ProdLoad.3gpp'

    def upload_to_aws(local_file, bucket, s3_file):
        # s3 = boto3.client('s3', aws_access_key_id=ACCESS_KEY,
        #                   aws_secret_access_key=SECRET_KEY)
        # print('S3',s3)
        try:
            s3.upload_file(local_file, bucket, s3_file)
            print("Upload Successful")
            return 'uploaded to AWS Successful'
        except FileNotFoundError:
            print("The file was not found")
            return False
        except NoCredentialsError:
            print("Credentials not available")
            return False

    # --------------------------------------------------------------------

    # Uploading the vdos in static folder first
    # ------------------------------
    UPLOAD_FOLDER = 'static/uploads'
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', '3gpp'])

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    # check if the post request has the file part
    if 'files[]' not in request.files:
        resp = jsonify({'message': 'No file part in the request'})
        resp.status_code = 400
        return resp

    files = request.files.getlist('files[]')

    errors = {}
    success = False

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            savePath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(savePath)

            success = True
            print('Started2')
            uploaded = upload_to_aws(savePath, bucket_name, filename)

        else:
            errors[file.filename] = 'File type is not allowed'

    if success and errors:
        errors['message'] = 'File(s) successfully uploaded'
        resp = jsonify(errors)
        resp.status_code = 206
        return resp
    if success:
        resp = jsonify({'message': 'Files successfully uploaded'})
        resp.status_code = 201
        return resp
    else:
        resp = jsonify(errors)
        resp.status_code = 400
        return resp

    return 'uploaded to AWS Successful'


@app.route('/testing', methods=['GET'])
def vdoDownload():
    print('working')
    DOWNLOAD_FOLDER = 'static/vdo_download'
    app.config['DOWNLOAD_FOLDER'] = DOWNLOAD_FOLDER

    channel_url = request.args.get('channel_name')

    try:  # trying to fetch vdo urls of the channel
        channel_url = Channel(channel_url)  # pytube processing
    except:
        return "ERROR - Could not collect the channel info. Make sure the channel url is valid "

    # fetching all videos
    all_video = channel_url.videos

    # no of videos  user wants fetch the data of
    vdo_limit = int(request.args.get('target_nunOf_vdos'))
    target_vdo_len = int(request.args.get('target_length'))

    counter = 0
    for vdo in all_video:
        output_path = os.path.join(app.config['DOWNLOAD_FOLDER'])
        fileName = vdo.video_id + '.3ggp'
        vdo.streams.first().download(output_path=output_path, filename=fileName)
        counter = counter + 1
        if counter > 1:
            break  # if the limit is reached

    # Zip file Initialization
    zipfolder = zipfile.ZipFile('Videofiles.zip', 'w', compression=zipfile.ZIP_STORED)  # Compression type

    # zip all the files which are inside in the folder
    for root, dirs, files in os.walk(app.config['DOWNLOAD_FOLDER']):
        for file in files:
            zip_dest_path = os.path.join(app.config['DOWNLOAD_FOLDER'], file)
            zipfolder.write(zip_dest_path)
    zipfolder.close()


    # return send_file('Audiofiles.zip',
    #                  mimetype='zip',
    #                  attachment_filename='Audiofiles.zip',
    #                  as_attachment=True)

    return 'vdo downloaded '

@app.route('/download')
def download():
    path = 'Videofiles.zip'
    return send_file(path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
