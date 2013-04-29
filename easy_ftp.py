#!/usr/bin/env python
from __future__ import with_statement
import logging
import os
import sys
import datetime
import time
import ftplib
import shutil
import urllib2
import contextlib
import socket
import signal

class TimeoutException(Exception):
    pass

class EasyFtpError(Exception):
    pass

def handle_timeout(signum, frame):
    raise TimeoutException( "Timed out. Error code: %i."%(signum) )

# Define the logger
LOG = logging.getLogger(__name__)

class FtpConnection:
    def __init__(self, ftp_remote_address, username=None, password=None, number_of_retries=0, cooldown_seconds = None ):
        """
        The constructor of the ftp connection.
        Automatically logs in and changes the working directory to the ftp path.
        """
        # Making sure this number is set to something positive.
        assert( number_of_retries >= 0 )

        # TODO: "root_path" is probably a incorrect name. Should be renamed to something a bit more appropriate.
        # Setting up.
        self.host, self.root_path = FtpConnection.split_ftp_host_and_path( ftp_remote_address )
        self.username = username
        self.password = password
        self.number_of_retries = number_of_retries

        # Internally...
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_timestamp = None
        
        # Login.
        LOG.debug( "Logging in to %s."%( self.host ) )
        self.ftp = ftplib.FTP( self.host )
        self._login()

        LOG.debug( "Changing remote path to %s."%( self.root_path ) )
        self.ftp.cwd( self.root_path )


    def _cooldown( self ):
        """
        Internal method.
        If self._cooldown_seconds is set in the constructor, this ftp client, will cool down for the
        number of speficied seconds, since last request, before making a new request.

        E.g. a timestamp is set when the last download FINISHED.
        If self._cooldown_seconds is 3 and a new request is made after 2 seconds, the program will sleep
        for 1 second before the next download is made.
        """
        if self._cooldown_seconds:
            LOG.debug( "Cooling down..." )
            if self._cooldown_timestamp:
                time_since_last_action_seconds = int( time.mktime(datetime.datetime.now().timetuple()) ) - self._cooldown_timestamp
                sleeptime_seconds = self._cooldown_seconds - time_since_last_action_seconds
                if sleeptime_seconds > 0:
                    LOG.debug( "Cooling down for %i second(s)"%(sleeptime_seconds) ) 
                    time.sleep( sleeptime_seconds  )


    def _cooldown_set_timestamp( self ):
        """
        Sets the timestamp used when cooling down.
        Only used if self._cooldown_seconds is specified.
        """
        if self._cooldown_seconds:
            LOG.debug( "Setting cooldown timestamp." )
            self._cooldown_timestamp = int(time.mktime(datetime.datetime.now().timetuple()))

    def login( self ):
        """
        Logs in to the ftp server.
        Retries once.
        Using credentials if given.
        """
        try:
            LOG.debug( "Logging in." )
            self._login()
        except:
            LOG.error( "Log in failed. Trying again." )
            LOG.error( sys.exc_info()[0] )
            try: self.close()
            except: pass
            self._login()
            LOG.error( "Login OK.")

        
    def _login( self ):
        """
        Logs in to the ftp server.
        If specified, cools down first.
        Using credentials if given.
        """
        self._cooldown()
        try:
            if self.username and self.password:
                LOG.debug( "Logging in using credentials." )
                self.ftp.login( self.username, self.password )
            else:
                LOG.debug( "Logging in to ftp server." )
                self.ftp.login()
        finally:
            self._cooldown_set_timestamp()


    def download_file( self, remote_file_address, destination_filename, timeout_seconds = None ):
        """
        Downloads a file, using _download_file.
        Times out, if specified.
        Retrying if specified in the constructor.
        """
        attempt_counter = 0
        while True:
            attempt_counter += 1
            try:
                if timeout_seconds:
                    # Timeout.
                    # How it works:
                    # A signal alarm is set to be activated in timeout_seconds. If it does,
                    # it is handled by the handle_timeout method (see top).
                    signal.signal( signal.SIGALRM, handle_timeout )
                    LOG.debug( "Setting timeout alarm: %s seconds"%( timeout_seconds ) )
                    # An alarm will be sent after timeout_seconds.
                    signal.alarm(timeout_seconds)
                # Try to download the file.
                LOG.debug( "Trying to download '%s' to '%s'."%( remote_file_address, destination_filename ))
                LOG.debug( "Attempt: %i/%i'."%( attempt_counter, self.number_of_retries ))
                if self._download_file( remote_file_address, destination_filename ):
                    # The file was downloaded!
                    if timeout_seconds:
                        # Cancel the alarm.
                        signal.alarm(0)
                        LOG.debug( "Timeout alarm cancelled." )
                    LOG.debug( "The file was successfully downloaded: '%s'."%( remote_file_address ))
                    return True
                else:
                    # The file was not downloaded.
                    # It did not time out, som the alarm should be cancelled.
                    if timeout_seconds:
                        # Cancel the alarm.
                        signal.alarm(0)
                        LOG.debug( "Timeout alarm cancelled." )
                    
                    # We have tried enough.
                    LOG.warning( "The file was NOT downloaded: '%s'."%( remote_file_address ) )
                    if attempt_counter > self.number_of_retries:
                        LOG.warning( "Will NOT try again." )
                        break
                    else:
                        LOG.warning( "Will try again." )
            except Exception, e:
                if attempt_counter > self.number_of_retries:
                    # If we reach this point, the number of retries has been exceeded.
                    # Just get out of the loop.
                    raise e

                # Output some error information.
                LOG.error( e )
                LOG.error( sys.exc_info()[0] )
                LOG.error("Download failed. Will try again." )

                # Sleeping for attempt_counter seconds, to be nice to the server, but also to give 
                # the problem some time to be repaired.
                # Increasing the number for every time. 2 seconds increments.
                two_seconds = 2
                sleeptime_seconds = attempt_counter * two_seconds
                LOG.error( "But first sleeping for %i seconds to be nice to the server."%( sleeptime_seconds ) )
                time.sleep( sleeptime_seconds )
        return False


    def _download_file( self, remote_file_address, destination_filename ):
        """
        Tries to download a file from the ftp host twice using ftplib. If that fails, tries using urllib2.
        Retries as specified in the constructor. No timeout... yet...

        First creates a tmp file. When download is completed, the file is renamed to the destination_filename.

        Cools down, if specified in the constructor, if needed.
        """
        self._cooldown()


        destination_filename_tmp = "%s.tmp"%( destination_filename )
        LOG.debug( "Tmp filename for '%s': '%s'."%( destination_filename, destination_filename_tmp )  )

        if os.path.isfile( destination_filename ):
            LOG.debug( "The destination file '%s' exists already. Deleting it.."%( destination_filename ) )
            os.remove( destination_filename )
        if os.path.isfile( destination_filename_tmp ):
            LOG.debug( "The tmp destination file '%s' exists already. Deleting it.."%( destination_filename_tmp  ) )
            os.remove( destination_filename_tmp )

        try:
            LOG.debug( "Downloading '%s' using ftplib to '%s'"%( remote_file_address, destination_filename_tmp ) )
            try:
                with open( destination_filename_tmp, 'wb' ) as local_file:
                    self.ftp.retrbinary( "RETR %s"%( remote_file_address ), local_file.write  )
                LOG.error( "File '%s' saved."%( destination_filename_tmp )  )
            except socket.error, e:
                # Most likely because the session has timed out, or something alike.
                # The solution seem to be to relogin.
                LOG.error( e )
                LOG.error( "Trying to relog in." )
                self.login()

                # Downloading the file again.
                LOG.error( "Trying to download again, using ftplib." )
                with open( destination_filename_tmp, 'wb' ) as local_file:
                    self.ftp.retrbinary( "RETR %s"%( remote_file_address ), local_file.write  )
                LOG.error( "File '%s' saved."%( destination_filename_tmp )  )
        except Exception, e:
            LOG.error( e )
            LOG.error( sys.exc_info()[0] )
            LOG.error( "Downloading file '%s' using ftplib failed. Trying using urllib2."%( remote_file_address ) )
            
            LOG.debug( "Building remote url..." )
            if remote_file_address.startswith( "ftp://" ):
                # Removing the ftp://. Making it possible to put in username and password later on.
                remote_url = remote_file_address.replace( "ftp://", "", 1 )
            elif remote_file_address.startswith( "/" ):
                # The reslut of the below should be the same as removing the ftp:// string...
                remote_url = "%s%s"%( self.host, remote_file_address )
            else:
                # This should again be the same as removing the ftp:// string above...
                remote_url = "%s%s/%s"%( self.host, self.root_path, remote_file_address )

            # Adding username and password if specified.
            if self.username and self.password:
                remote_url = "%s:%s@%s"%( self.username, self.password, remote_url )

            # Putting the ftp:// string back in.
            remote_url = "ftp://%s"%( remote_url )

            # Downloading the file, using urllib2.
            LOG.error( "Downloading file, '%s' to '%s' using urllib2."%(remote_url, destination_filename_tmp))
            with contextlib.closing( urllib2.urlopen( remote_url )) as remote_file:
                LOG.debug( "Remote file, %s, opened."%( remote_url ) )
                with open( destination_filename_tmp, 'wb' ) as local_file:
                    LOG.debug( "Local file: '%s'."%( destination_filename_tmp ) )
                    shutil.copyfileobj( remote_file, local_file )
                    LOG.error( "File '%s' saved."%( destination_filename_tmp)  )
        finally:
            # Setting the cooldown timestamp.
            self._cooldown_set_timestamp()

        
        # Checking that the tmp filename has a size larger than 0,
        # and if it does rename the tmp file to the destination filename.
        if os.path.isfile( destination_filename_tmp ):
            if os.path.getsize( destination_filename_tmp ) > 0:
                LOG.debug( "Moving '%s' to '%s'."%( destination_filename_tmp, destination_filename ) )
                shutil.move( destination_filename_tmp, destination_filename )
                LOG.info( "File '%s' saved."%( destination_filename ) )
                return True
            else:
                LOG.warning( "'%s' had size zero... will be removed so that it can be downloaded later."%( destination_filename_tmp ) )
                # TODO: Check that the filesizes are different both remotely and locally before deleting.
                os.remove( destination_filename_tmp )
                LOG.warning( "'%s' removed."%( destination_filename_tmp ) )
        return False
                       

    @staticmethod
    def split_ftp_host_and_path( ftp_remote_address ):
        """
        Splits the ftp address into host and path.
        
        What it does is remove the "ftp://" in the beginning of the address, and
        then split the string on the first "/", and then add "/" to the last part,
        to make it clear that it is the root path on the host.
        """
        if ftp_remote_address.startswith("ftp://"):
            LOG.debug( "Removing ftp:// from remote address." )
            ftp_remote_address = ftp_remote_address.replace( "ftp://", "", 1 )
        LOG.debug( ftp_remote_address )
        remote_host, root_path = ftp_remote_address.split( "/", 1 )
        LOG.debug( "Remote address, '%s', splitted into '%s' and '%s'."%( ftp_remote_address, remote_host, root_path ) )

        if not root_path.startswith("/"):
            root_path = "/%s"%( root_path )
        LOG.debug( "Making sure the remote root path allways is absolute, '%s'."%( root_path ) )
        return remote_host, root_path

    def __enter__( self ):
        """
        This function is called when using with statements.

        Example::
            with FtpConnection( <ftp_address> ) as ftp:
                print ftp.get_files()

        Here, the "ftp" becomes the "self".
        """
        return self

    def __exit__(self, type, value, traceback):
        """
        This function is the one called when exiting the scope of the
        with statement. Se e.g. __enter__.
        """
        self.close()
    
    def close( self ):
        """
        Tries to close down the ftp connection in a polite way.
        """
        try:
            self.ftp.quit()
            self.ftp.close()
            LOG.debug( "FTP connection closed." )
        except:
            LOG.warning( sys.exc_info()[0] )
            LOG.warning( "Exception raised when closing ftp connection." )

    def get_directories( self, path=None, timeout_seconds = None ):
        """
        Gets a list of directories for a specific path. If path is not given,
        the directories in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "d", path, timeout_seconds = timeout_seconds )

    def get_filenames( self, path=None, timeout_seconds = None ):
        """
        Gets a list of files for a specific path. If path is not given,
        the files in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "-", path, timeout_seconds = timeout_seconds )

    def get_links( self, path=None, timeout_seconds = None ):
        """
        Gets a list of links for a specific path. If path is not given,
        the links in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "l", path, timeout_seconds = timeout_seconds )

    def get_entries_starting_with( self, startswith, path = None, timeout_seconds = None ):
        """
        Parses the list content string and returns a list of all the entries starting with
        "startswith".
        """
        entries = []
        contents = self.list_contents( path, timeout_seconds=timeout_seconds )
        for content in contents:
            # TODO: Return an object containing some more information about the files / directories / links.
            # There is more info in the string, which e.g. could be parsed into an object.
            if content.startswith( startswith ):
                # content e.g.: drwxrwxr-x    2 12546    101        159744 Mar 13 21:51 2012.354
                entries.append( content.split(" ")[-1] )
        return entries

    def list_contents( self, path=None, timeout_seconds = None ):
        """
        Lists the contents for a given path.
        When the contents has been listed, the working directory is 
        Retries once if an error occurs.
        """
        attempt_counter = 0
        while True:
            attempt_counter += 1
            try:
                if timeout_seconds:
                    # Timeout.
                    # How it works:
                    # A signal alarm is set to be activated in timeout_seconds. If it does,
                    # it is handled by the handle_timeout method (see top).
                    # The alarm is cancelled in the finally clause, where it will only go
                    # if the file was downloaded.
                    signal.signal( signal.SIGALRM, handle_timeout )
                    LOG.debug( "Setting timeout alarm: %s seconds"%( timeout_seconds ) )
                    # An alarm will be sent after timeout_seconds.
                    signal.alarm(timeout_seconds)
                try:
                    return self._list_contents( path )
                except socket.error, e:
                    # Most likely because the session has timed out, or something alike.
                    # The solution seem to be to relogin.
                    LOG.error( "Failed listing contentes. Retrying." )
                    LOG.error( e )
                    LOG.error( "Trying to log in again." )
                    self.login()

                    LOG.error( "Trying to list contents again." )
                    return self._list_contents( path )
                finally:
                    if timeout_seconds:
                        # Cancel the alarm.
                        signal.alarm(0)
                        # As this is in a finally clause, it will happen all the time.
                        LOG.debug( "Timeout alarm cancelled." )

            except Exception, e:
                if attempt_counter > self.number_of_retries:
                    # If we reach this point, the number of retries has been exceeded.
                    # Just get out of the loop.
                    raise e
                LOG.error( e )
                LOG.error( sys.exc_info()[0] )
                LOG.error("List content failed. Retrying: %i/%i."%( attempt_counter, self.number_of_retries ))

            if attempt_counter > self.number_of_retries:
                # If we reach this point, the number of retries has been exceeded.
                raise EasyFtpError( "Could not list the content of %s after %i attempts."%(path, attempt_counter) )



    def _list_contents( self, path=None ):
        """
        Changes the directory to the path, if given, and list all the contents in that directory. Then automatically
        changes the working directory back to the ftp address root.

        Returns a list of lines that the ftp server returns.
        """
        self._cooldown()
        try:
            if path:
                LOG.debug("Changing path to %s"%(path))
                self.ftp.cwd( path )
            contents = []
            self.ftp.retrlines( "LIST", contents.append )
            self.ftp.cwd( self.root_path )
            return contents
        finally:
            self._cooldown_set_timestamp()
        

if __name__ == "__main__":
    try:
        import argparse
    except Exception, e:
        print ""
        print "Try running 'sudo apt-get install python-argparse' or 'sudo easy_install argparse'!!"
        print ""
        raise e

    def string2date( date_string ):
        return datetime.datetime.strptime( date_string, '%Y-%m-%d' ).date()

    def directory( dir_path ):
        if not os.path.isdir( dir_path ):
            raise argparse.ArgumentTypeError( "'%s' does not exist. Please specify save directory!"%(dir_path))
        return dir_path

    parser = argparse.ArgumentParser( description='Connect to an ftp server and list the files, directories and links in the directory.' )
    parser.add_argument( "remote_source_address"
                         , type=str
                         , help='Remote source adress, e.g. ftp://example.com/some/nice/path'
                         )
    parser.add_argument( '-u', '--username'
                         , type=str
                         , help='Some directory, that exists, if set (optional)...'
                         )
    parser.add_argument( '-p', '--password'
                         , type=str
                         , help="Some string."
                         )
    parser.add_argument( '-d', '--debug', action='store_true', help="Output debugging information." )
    parser.add_argument( '--log_filename', type=str, help="File used to output logging information." )

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig( filename=args.log_filename, level=logging.DEBUG )
    else:
        logging.basicConfig( filename=args.log_filename, level=logging.INFO )

    if args.username and not args.password:
        raise argparse.ArgumentTypeError( "Both username and password must be set" )
    
    # Output what is in the args variable.
    LOG.debug(args)

    with FtpConnection( args.remote_source_address, args.username, args.password ) as ftp:
        directories = ftp.get_directories()
        files = ftp.get_filenames()
        links = ftp.get_links()

        print "Remote root directory:", ftp.root_path
        print "Number of directories:", len( directories )
        print "Number of files:", len(files)
        print "Number of links:", len(links)
