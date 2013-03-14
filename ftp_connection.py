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
        """
        The constructor of the ftp connection.
        Automatically logs in and changes the working directory to the ftp path.
        """
        # TODO: "root_path" is probably a incorrect name. Should be renamed to something a bit more appropriate.
        self.host, self.root_path = FtpConnection.split_ftp_host_and_path( ftp_remote_address )
        self.username = username
        self.password = password

        LOG.debug( "Logging in to %s."%( self.host ) )
        self.ftp = ftplib.FTP( self.host )
        self.login()

        LOG.debug( "Changing remote path to %s."%( self.root_path ) )
        self.ftp.cwd( self.root_path )


    def login(self):
        """
        Tries to login to the ftp server.
        Using credentials if given.
        """
        if self.username and self.password:
            LOG.debug( "Logging in using credentials." )
            self.ftp.login( self.username, self.password )
        else:
            LOG.debug( "Logging in to ftp server." )
            self.ftp.login()


    def download_file( self, remote_file_address, destination_filename ):
        """
        Tries to download a file from the ftp host twice using ftplib. If that fails, tries using urllib2.
        In total 3 attemts. No timeout.
        """

        # TODO: Add timeout.
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
                # TODO: Check that the filesizes are different both remotely and locally before deleting.
                os.remove( destination_filename )
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
            LOG.warning( "Exception raised when closing ftp connection." )

    def get_directories( self, path=None ):
        """
        Gets a list of directories for a specific path. If path is not given,
        the directories in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "d", path )

    def get_filenames( self, path=None ):
        """
        Gets a list of files for a specific path. If path is not given,
        the files in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "-", path )

    def get_links( self, path=None ):
        """
        Gets a list of links for a specific path. If path is not given,
        the links in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with( "l", path )

    def get_entries_starting_with( self, startswith, path = None ):
        """
        Parses the list content string and returns a list of all the entries starting with
        "startswith".
        """
        entries = []
        contents = self.list_contents( path )
        for content in contents:
            # TODO: Return an object containing some more information about the files / directories / links.
            # There is more info in the string, which e.g. could be parsed into an object.
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
        """
        Changes the directory to the path, if given, and list all the contents in that directory. Then automatically
        changes the working directory back to the ftp address root.

        Returns a list of lines that the ftp server returns.
        """
        if path:
            LOG.debug("Changing path to %s"%(path))
            self.ftp.cwd( path )
        contents = []
        self.ftp.retrlines( "LIST", contents.append )
        self.ftp.cwd( self.root_path )
        return contents
        

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
