import boto3
import json
import sys
import pika
import time
import traceback
import requests
from python_kerberos_vault_integrator.KerberosVaultIntegrator import KerberosVaultIntegrator
from confluent_kafka import Producer, Consumer



# Parent class with the methods each child class should implement
class MessageBroker:
    """ A base class representing a message broker.

    This class defines the common interface for interacting with message brokers,
    such as receiving messages, sending messages, and closing the connection.

    Methods:
    --------
    ReceiveMessages: Receives messages from the message broker.
    SendMessage(self): Sends a message through the message broker.
    Close(self): Closes the connection to the message broker.
    """

    def __init__(self) -> None:
        """ Initializes the MessageBroker object.
        """
        pass

    def ReceiveMessages(self):
        """ Receives messages from the message broker.
        """
        raise NotImplementedError("ReceiveMessages method must be implemented in child class")

    def SendMessage(self):
        """ Sends a message through the message broker.
        """
        raise NotImplementedError("SendMessage method must be implemented in child class")

    def Close(self):
        """ Closes the connection to the message broker.
        """
        raise NotImplementedError("Close method must be implemented in child class")
    


# Child classes with the implementation specific to each message broker
# RabbitMQ
class RabbitMQ(MessageBroker):
    """ A class representing a message broker using RabbitMQ.

    This class inherits from the MessageBroker base class and provides
    implementation specific to RabbitMQ.
    """

    def __init__(self, queue_name: str = '', target_queue_name: str = '', exchange: str = '', host: str = '', username: str = '', password: str = ''):
        """ Initializes the RabbitMQ object.

        Parameters:
        -----------
        queue_name : str
            The name of the RabbitMQ queue. Defaults to an empty string.
        exchange : str
            The name of the RabbitMQ exchange. Defaults to an empty string.
        host : str
            The hostname of the RabbitMQ server. Defaults to an empty string.
        username : str
            The username to authenticate with RabbitMQ. Defaults to an empty string.
        password : str
            The password to authenticate with RabbitMQ. Defaults to an empty string.
        
        """

        self.queue_name = queue_name
        self.exchange = exchange
        self.host = host
        self.username = username
        self.password = password
        self.target_queue_name = target_queue_name
        
        # Establish connection to RabbitMQ
        self.Connect(host, username, password)

        # Declare quorum queue
        self.readChannel.queue_declare(queue=self.queue_name, durable=True, arguments={
                                       'x-queue-type': 'quorum'})

        # Check if connection is open otherwise kill
        if not self.connection.is_open:
            print("Connection to RabbitMQ is not open")
            sys.exit(1)

    def Connect(self) -> None:
        """ Establishes a connection to RabbitMQ.
        """

        host = self.host
        username = self.username
        password = self.password

        # Check if required credentials are provided
        if host and username and password:
            protocol = ''
            if host.find('amqp://') != -1:
                protocol = 'amqp'
                host = host.replace('amqp://', '')
            if host.find('amqps://') != -1:
                protocol = 'amqps'
                host = host.replace('amqps://', '')

            if not protocol:
                url_string = "amqp://" + username + ":" + password + \
                    "@" + host + "/"
            else:
                url_string = protocol + "://" + username + ":" + password + \
                    "@" + host + "/"

            url_parameter = pika.URLParameters(url_string)
            self.connection = pika.BlockingConnection(url_parameter)
            self.readChannel = self.connection.channel()
            self.publishChannel = self.connection.channel()

    def ReceiveMessages(self) -> list[dict]:
        """ Receives messages from the RabbitMQ queue.
        """

        # Check if connection to RabbitMQ is open, if not, reconnect
        if not self.connection.is_open:
            print("Connection to RabbitMQ is not open")
            self.Connect()

        # Check if readChannel is closed, if yes, reinitialize
        if self.readChannel.is_closed:
            print("Channel to RabbitMQ is closed")
            self.readChannel = self.connection.channel()

        # Fetch a message from the queue
        method_frame, header_frame, body = self.readChannel.basic_get(
            self.queue_name, auto_ack=True)
        
        # If no message available, sleep and return empty list
        if body is None:
            time.sleep(3.0)
            return []

        # Otherwise, return the received message
        return [json.loads(body)]

    def SendMessage(self, message: str):
        """ Sends a message to the RabbitMQ queue.
        
        Parameters:
        -----------
        message : str
            The message to send.

        """

        try:
            # Publish the message to the RabbitMQ exchange
            self.publishChannel.basic_publish(
                exchange=self.exchange, routing_key=self.target_queue_name, body=message)
        
        # Handle connection and channel closure exceptions
        except pika.exceptions.ConnectionClosed:
            print('Reconnecting to queue')
            self.Connect()
            self.publishChannel.basic_publish(
                exchange=self.exchange, routing_key=self.target_queue_name, body=message)
        except pika.exceptions.ChannelClosed:
            print('Reconnecting to queue')
            self.publishChannel = self.connection.channel()
            self.publishChannel.basic_publish(
                exchange=self.exchange, routing_key=self.target_queue_name, body=message)

    def Close(self) -> bool:
        """ Closes the connection to RabbitMQ.
        """

        self.connection.close()
        return True



# SQS, TO BE TESTED
class SQS(MessageBroker):
    """ A class representing a message broker using Amazon Simple Queue Service (SQS).

    This class inherits from the MessageBroker base class and provides
    implementation specific to SQS.
    """

    def __init__(self, queue_name: str = '', aws_access_key_id: str = '', aws_secret_access_key: str = ''):
        """ Initializes the SQS object.

        Parameters:
        -----------
        queue_name : str
            The name of the SQS queue. Defaults to an empty string.
        aws_access_key_id : str
            The AWS access key ID. Defaults to an empty string.
        aws_secret_access_key : str
            The AWS secret access key. Defaults to an empty string.
        
        """

        # Set the queue_name attribute
        self.queue_name = queue_name

        # Initialize SQS resource with the specified AWS credentials and region
        self.sqs = boto3.resource('sqs', use_ssl=True,
                                  region_name='eu-west-1',
                                  aws_access_key_id=aws_access_key_id,
                                  aws_secret_access_key=aws_secret_access_key
                                  )
        
        # Get the SQS queue object by its name
        self.queue = self.sqs.get_queue_by_name(queue_name=self.queue_name)

    def ReceiveMessages(self) -> list[dict]:
        """ Receives messages from the SQS queue.
        """

        # List to store received messages
        messages = []

        # Iterate over messages received from the queue
        for message in self.queue.receive_messages(MessageAttributeNames=['Author'],
                                                   MaxNumberOfMessages=3,
                                                   WaitTimeSeconds=20,
                                                   VisibilityTimeout=10):
            # Delete the message from the FIFO queue, so other consumers can start processing
            response = message.delete()
            
            # If message deletion is successful, append the message to the list
            if response['ResponseMetadata']['HTTPStatusCode'] == 200:
                messages.append(json.loads(message.body))
        
        # Return the list of received messages
        return messages

    def SendMessage(self, message: str):
        """ Sends a message to the SQS queue.
        
        Parameters:
        -----------
        message : str
            The message to send to the queue.
        """

        # Send the message to the SQS queue
        self.queue.send_message(MessageBody=message)

    def Close(self) -> bool:
        """ Closes the connection to the SQS queue.
        """

        # Since SQS doesn't require explicit connection management, 
        # we just return True to indicate successful closure
        return True



# Kafka, TO BE TESTED
class Kafka(MessageBroker):
    """ A class representing a message broker using Apache Kafka.

    This class inherits from the MessageBroker base class and provides
    implementation specific to Apache Kafka.
    """

    def __init__(self, queue_name: str = '', broker: str = '', group_id: str = '', mechanism: str = '', security: str = '', username: str = '', password: str = ''):
        """ Initializes the Kafka object.

        Parameters:
        -----------
        queue_name : str
            The name of the Kafka topic. Defaults to an empty string.
        broker : str, optional
            The hostname and port of the Kafka broker. Defaults to an empty string.
        group_id : str
            The Kafka consumer group ID. Defaults to an empty string.
        mechanism : str
            The Kafka SASL mechanism. Defaults to an empty string.
        security : str
            The Kafka security protocol. Defaults to an empty string.
        username : str
            The username to authenticate with Kafka. Defaults to an empty string.
        password : str
            The password to authenticate with Kafka. Defaults to an empty string.

        """

        # Set the queue_name attribute
        self.queue_name = queue_name
        
        # Kafka consumer settings
        kafkaC_settings = {
            'bootstrap.servers': broker,
            "group.id":             group_id,
            "session.timeout.ms":         60000,
            "max.poll.interval.ms":       60000,
            "queued.max.messages.kbytes": 1000000,
            "auto.offset.reset":          "earliest",
            "sasl.mechanisms":   mechanism,
            "security.protocol": security,
            "sasl.username":     username,
            "sasl.password":     password,
        }
        
        # Initialize Kafka consumer
        self.kafka_consumer = Consumer(kafkaC_settings)
        self.kafka_consumer.subscribe([self.queue_name])

        # Kafka producer settings
        kafkaP_settings = {
            'bootstrap.servers': broker,
            "sasl.mechanisms":   mechanism,
            "security.protocol": security,
            "sasl.username":     username,
            "sasl.password":     password,
        }
        
        # Initialize Kafka producer
        self.kafka_producer = Producer(kafkaP_settings)

    def ReceiveMessages(self) -> list[dict]:
        """ Receives messages from the Kafka topic.
        """

        # Poll for messages from the Kafka consumer
        msg = self.kafka_consumer.poll(timeout=3.0)
        
        # If no message is received, return an empty list
        if msg is None:
            return []
        
        # Otherwise, return the received message
        return [json.loads(msg.value())]

    def delivery_callback(self, err, msg):
        """ Callback function to handle message delivery.
        """

        # If there's an error, write it to stderr
        if err:
            sys.stderr.write('%% Message failed delivery: %s\n' % err)
        else:
            # Otherwise, write the delivery confirmation
            sys.stderr.write('%% Message delivered to %s [%d] @ %d\n' %
                             (msg.topic(), msg.partition(), msg.offset()))

    def SendMessage(self, message: str):
        """ Sends a message to the Kafka topic.
        """

        try:
            # Produce the message to the Kafka topic
            self.kafka_producer.produce(
                'kcloud-analysis-queue', message, callback=self.delivery_callback)
            
            # Poll for events from the Kafka producer
            self.kafka_producer.poll(0)
        
        except BufferError as e:
            # If there's a buffer error, print it to stderr
            print(e, file=sys.stderr)
            # Poll for events from the Kafka producer
            self.kafka_producer.poll(1)

    def Close(self) -> bool:
        """ Closes the connection to Kafka.
        """

        # Close the Kafka consumer and producer, and flush the producer's messages
        self.kafka_consumer.close()
        self.kafka_producer.flush()
        self.kafka_producer.close()
        
        return True
    


class KerberosVaultIntegrated(MessageBroker):
    def __init__(self, 
                 rmq_source_queue_name: str = '', rmq_target_queue_name: str = '', rmq_exchange: str = '', rmq_host: str = '', rmq_username: str = '', rmq_password: str = '',
                 aws_source_queue_name: str = '', aws_access_key_id: str = '', aws_secret_access_key: str = '',
                 kafka_source_queue_name: str = '', kafka_broker: str = '', kafka_group_id: str = '', kafka_mechanism: str = '', kafka_security: str = '', kafka_username: str = '', kafka_password: str = '',
                 storage_uri: str = '', storage_access_key: str = '', storage_secret: str = ''
                ):
        """ Initializes the QueueProcessor object with necessary attributes.
        Uses the provided source queue system to initialize the queue object, and initializes the Kerberos Vault Integrator.

        Parameters:
        -----------
        
        RabbitMQ Parameters:
        rmq_source_queue_name : str
            The name of the source queue in RabbitMQ.
        rmq_target_queue_name : str
            The name of the target queue in RabbitMQ.
        rmq_exchange : str
            The exchange name in RabbitMQ.
        rmq_host : str
            The host name of the RabbitMQ server.
        rmq_username : str
            The username for RabbitMQ server.
        rmq_password : str
            The password for RabbitMQ server.

        AWS SQS Parameters:
        aws_source_queue_name : str
            The name of the source queue in AWS SQS.
        aws_access_key_id : str
            The access key for AWS SQS.
        aws_secret_access_key : str
            The secret key for AWS SQS.

        Kafka Parameters:
        kafka_source_queue_name : str
            The name of the source queue in Kafka.
        kafka_broker : str
            The broker URL for Kafka.
        kafka_group_id : str
            The group ID for Kafka.
        kafka_mechanism : str
            The security mechanism for Kafka.
        kafka_security : str
            The security protocol for Kafka.
        kafka_username : str
            The username for Kafka.
        kafka_password : str
            The password for Kafka.

        Kerberos Vault Integrator Parameters:
        storage_uri : str
            The URI of the storage service.
        storage_access_key : str
            The access key for the storage service.
        storage_secret : str
            The secret key for the storage service.
        
        """
        
        # Initialize Kerberos Vault Integrator
        self.kerberos_vault_integrator = KerberosVaultIntegrator.KerberosVaultIntegrator(storage_uri, storage_access_key, storage_secret)

        # Initialize source queue based on the provided source queue system
        if rmq_source_queue_name != '':
            self.queue = RabbitMQ(queue_name = rmq_source_queue_name, target_queue_name = rmq_target_queue_name, exchange = rmq_exchange, host = rmq_host, username = rmq_username, password = rmq_password)
        
        elif aws_source_queue_name != '':
            self.queue = SQS(queue_name  = aws_source_queue_name, aws_access_key_id = aws_access_key_id, aws_secret_access_key = aws_secret_access_key)
        
        elif kafka_source_queue_name != '':
            self.queue = Kafka(queue_name = kafka_source_queue_name, broker = kafka_broker, group_id = kafka_group_id, mechanism = kafka_mechanism, security = kafka_security, username = kafka_username, password = kafka_password)
        
        else:
            # Raise an exception if an invalid source queue system is provided
            raise ValueError("Please provide a source_queue_name for either RabbitMQ, AWS SQS, or Kafka with the necessary credentials")
        

    
    def ReceiveMessages(self, type: str = '', filepath: str = ''):
        """ Processes message received from the source queue, fetches associated data from storage, and performs actions.

        Parameters:
        -----------
        type : str
            The type of message to be processed (video). Default is an empty string.
            if type is 'video', the message is processed and video file is created. Filepath is returned.
            else, the message response is returned.
        
        filepath : str
            The path where the video file is to be saved. Default is an empty string.
        """

        try:
            # Receive messages from the source queue
            messages = self.queue.ReceiveMessages()

        except Exception as e:
            print('Error occurred while trying to receive message:')
            print(e)
            traceback.print_exc()
            pass


        # Process messages until successful response is received or all messages are processed
        for body in messages:

            # Update storage-related information if available in message payload
            if "data" in body:
                self.kerberos_vault_integrator.update_storage_info(body['data'])

            # Create headers for accessing storage service
            headers = self.kerberos_vault_integrator.create_headers(body['payload']['key'], body['source'])

            try:
                # Fetch data associated with the message from storage service
                resp = requests.get(self.kerberos_vault_integrator.storage_uri + "/storage/blob", headers=headers, timeout=10)

                if resp is None or resp.status_code != 200:
                    print('None response or non-200 status code, skipping...')
                    continue

                if type == 'video':
                    # From the received requested data, reconstruct a video-file.
                    # This creates a video-file in the data folder, containing the recording.
                    with open(filepath, 'wb') as output:
                        output.write(resp.content)
            
                    return filepath
                
                else:
                    return resp
                
            except Exception as x:
                print('Error occurred while trying to fetch data from storage:')
                print(x)
                traceback.print_exc()
                pass
    


    def SendMessage(self, message):
        """ Sends message to the target queue.

        Parameters:
        -----------
        message : dict
            The message to be sent to the target queue.
        """

        # Send message to the target queue
        self.queue.SendMessage(message)



    def Close(self):
        """ Closes the connection to the source queue.
        """

        # Close the connection to the source queue
        self.queue.Close()