#!/usr/bin/env python
from __future__ import with_statement
import logging
import os
import sys
import datetime
import ftplib
import shutil
import urllib2
import contextlib
import socket

# Define the logger
LOG = logging.getLogger(__name__)

class FtpConnection:
    def __init__(self, ftp_remote_address, username=None, password=None ):
        self.host, self.root_path = ftp_connection.split_ftp_host_and_path( ftp_remote_address )
        self.username = username
        self.password = password
        LOG.debug( "Logging in to %s."%( self.host ) )
        self.ftp = ftplib.FTP( self.host )
        self.login()

        LOG.debug( "Changing remote path to %s."%( self.root_path ) )
        self.ftp.cwd( self.root_path )


    def login(self):
        if self.username and self.password:
            LOG.debug( "Logging in using credentials." )
            self.ftp.login( self.username, self.password )
        else:
            LOG.debug( "Logging in to ftp server." )
            self.ftp.login()


    def download_file( self, remote_file_address, destination_filename ):
        try:
            LOG.debug( "Downloading '%s' using ftplib to '%s'"%( remote_file_address, destination_filename ) )
            try:
                with open( destination_filename, 'wb' ) as local_file:
                    self.ftp.retrbinary( "RETR %s"%( remote_file_address ), local_file.write  )
            except socket.error, e:
                LOG.error( e )
                LOG.error( "Trying to relog in." )
                self.login()
                LOG.error( "Trying to download again, using ftplib." )
                with open( destination_filename, 'wb' ) as local_file:
                    self.ftp.retrbinary( "RETR %s"%( remote_file_address ), local_file.write  )
                LOG.error( "File '%s' saved."%( destination_filename)  )
        except:
            try:
                LOG.error( "Downloading file '%s' using ftplib failed. Trying using urllib2."%( remote_file_address ) )
                if os.path.isfile( destination_filename ):
                    LOG.error( "The file was partially downloaded. Remove it first, as it may not be complete.: '%s'."%( destination_filename ) )
                    os.remove( destination_filename )
                    LOG.error( "File removed: '%s'."%( destination_filename) )

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

                # Adding username and password
                if self.username and self.password:
                    remote_url = "%s:%s@%s"%( self.username, self.password, remote_url )

                # Adding ftp:// back.
                remote_url = "ftp://%s"%( remote_url )

                LOG.error( "Downloading file, '%s' to '%s' using urllib2."%(remote_url, destination_filename))
                with contextlib.closing( urllib2.urlopen( remote_url )) as remote_file:
                    LOG.debug( "Remote file, %s, opened."%( remote_url ) )
                    with open( destination_filename, 'wb' ) as local_file:
                        LOG.debug( "Local file: '%s'."%( destination_filename ) )
                        shutil.copyfileobj( remote_file, local_file )
                        LOG.error( "File '%s' saved."%( destination_filename)  )
            except:
                LOG.error( "Downloading '%s' failed permanentely."%( remote_file_address ) ) 

        if os.path.isfile( destination_filename ):
            if os.path.getsize( destination_filename ) > 0:
                return True
            else:
                LOG.warning( "'%s' had size zero... will be removed so that it can be downloaded later."%( destination_filename ) )
                os.remove( destination_filename )
        return False
                       

    @staticmethod
    def split_ftp_host_and_path( ftp_remote_address ):
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
        return self

    def __exit__(self, type, value, traceback):
        self.close()
    
    def close( self ):
        try:
            self.ftp.quit()
            self.ftp.close()
            LOG.debug( "FTP connection closed." )
        except:
            LOG.warning( "Exception raised when closing ftp connection." )

    def get_directories( self, path=None ):
        return self.get_entries_starting_with( "d", path )

    def get_filenames( self, path=None ):
        return self.get_entries_starting_with( "-", path )

    def get_links( self, path=None ):
        return self.get_entries_starting_with( "l", path )

    def get_entries_starting_with( self, startswith, path = None ):
        entries = []
        contents = self.list_contents( path )
        for content in contents:
            if content.startswith( startswith ):
                entries.append( content.split(" ")[-1] )
        return entries

    def list_contents( self, path=None ):
        """
        Lists the contents for a given path.
        When the contents has been listed, the working directory is 
        Retries once if an error occurs.
        """
        try:
            return self._list_contents( path )
        except:
            LOG.error( "Failed listing contentes. Retrying." )
            LOG.error( "Trying to log in again." )
            self.login()
            LOG.error( "Trying to list contents again." )
            return self._list_contents( path )

    def _list_contents( self, path=None ):
        if path:
            LOG.debug("Changing path to %s"%(path))
            self.ftp.cwd( path )
        contents = []
        self.ftp.retrlines( "LIST", contents.append )
        self.ftp.cwd( self.root_path )
        return contents
        

if __name__ == "__main__":

    # Uncomment if root privileges are required.
    # if os.geteuid() != 0:
    #    sys.exit("Must run as sudo!")

    try:
        import argparse
    except Exception, e:
        print ""
        print "Try running 'sudo apt-get install python-argparse' or 'sudo easy_install argparse'!!"
        print ""
        raise e

    def string2date( date_string ):
        # argparse.ArgumentTypeError()
        return datetime.datetime.strptime( date_string, '%Y-%m-%d' ).date()

    def directory( dir_path ):
        if not os.path.isdir( dir_path ):
            raise argparse.ArgumentTypeError( "'%s' does not exist. Please specify save directory!"%(dir_path))
        return dir_path

    parser = argparse.ArgumentParser( description='Connect to an ftp server and list the files, directories and links in the directory.' )
    parser.add_argument( "remote_source_address"
                         , type=str
                         , help='Remote source adress.'
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

    with ftp_connection( args.remote_source_address, args.username, args.password ) as ftp:
        directories = ftp.get_directories( ftp.root_path )
        
        files = ftp.get_filenames()
        for file in files:
            print file
        print len(files)
        print ftp.get_links( ftp.root_path )
