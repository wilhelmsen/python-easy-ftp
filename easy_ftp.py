#!/usr/bin/env python
# coding: utf-8
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
import multiprocessing
import errno

"""
An easy wrapper for the native ftplib in python.

Source: https://github.com/wilhelmsen/python-easy-ftp

Examples:
    import easy_ftp
    
    with easy_ftp.FTP( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        directories = ftp.get_directories()
        files = ftp.get_filenames()
        links = ftp.get_links()
        
        if ftp.download_file( "/<some dir path>/<filename>", destination_filename ):
            print "Files was downloaded."
        else:
            print "File was not downloaded."

    with easy_ftp.FTP( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        ftp.download_file( "/ftp/root/path/fish.txt", destination_filename ):
        ftp.download_file( "fish.txt", destination_filename ):

    with easy_ftp.FTP( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
    	 filenames_1 = ftp.get_filenames( "/ftp/root/path/with/fish/file/" )
         filenames_2 = ftp.get_filenames( "with/fish/file/" )


"""

# Define the logger
logging.basicConfig()
LOG = logging.getLogger(__name__)

# Exceptions / errors.
class TimeoutError(Exception):
    pass

class RetryError(Exception):
    pass

class EasyFtpError(Exception):
    pass

# Timeout decorator.
def timeout(seconds):
    """
    Decorator that times out after some time.
    An alarm is set. If the function does not finish before the alarm,
    a TimeoutError is raised. Else, the alarm is cancelled.
    """
    LOG.debug("Timeout: Timeout decorator.")

    def wrapper(function):
        # return function if we are running with zero timeout
        if seconds in (None, 0): 
            return function

        def _handle_timeout(signum, frame):
            """Internal function to handle the alarm."""
            raise TimeoutError("Timeout: Timed out after %i second(s)! Error code: %i."%(seconds, signum))

        def inner(*args, **kwargs):
            """Inner function that sets the alarm."""
            LOG.debug("Timeout: Setting alarm, %i second(s)."%(seconds))
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                LOG.debug("Timeout: Calling function.")
                result = function(*args, **kwargs)
            except Exception, e:
                LOG.error("Timeout: Raising timeouterror: %s"%(str(e)))
                raise e
            finally:
                LOG.debug("Timeout: Alarm cancelled.")
                signal.alarm(0)
            return result
        return inner
    return wrapper

# Retry decorator.
def retry(number_of_retries, sleep_factor = 1):
    """
    Decorator that retries to call a function if it fails with an exception.
    Retries the specified number of times.
    If the limit is reached, a RetryError is raised.
    """
    LOG.debug("Retry: Retry decorator.")
    assert(sleep_factor >= 0)
    
    def wrapper(function):
        # Just return function if no retries.
        if number_of_retries in (None, 0): 
            LOG.debug("Retry: Not going to retry.")
            return function

        # Does the loop.
        def inner(*args, **kwargs):
            counter = 1
            while counter <= number_of_retries:
                LOG.debug("Retry: Attempt %i/%i."%(counter, number_of_retries))
                try:
                    LOG.debug("Retry (%i/%i): Calling"%(counter, number_of_retries))
                    result = function(*args, **kwargs)
                    return result
                except socket.error, e:
                    # Most likely because the session has timed out, or something alike.
                    # The solution seem to be to relogin. No need to continue.
                    LOG.debug("Retry (%i/%i): Socket error, %s. Will probably need to relogin. Will not retry using the decorator."%(counter, number_of_retries, str(e)))
                    raise e
                except Exception, e:
                    LOG.error("Retry (%i/%i): Error in retry: %s."%(counter, number_of_retries, str(e)))
                    if sleep_factor > 0:
                        sleeptime = sleep_factor * counter + (sleep_factor * (counter-1) * 10)
                        LOG.debug("Retry (%i/%i): Sleeping before retrying: %i second(s)."%(counter, number_of_retries, sleeptime))
                        time.sleep(sleeptime)
                    counter += 1
            raise RetryError("Retry: Failed %i times."%(number_of_retries))
        return inner
    return wrapper


class FTP:
    """
    The class that creates the ftp-connection.
    """
    def __init__(self, ftp_remote_address, username=None, password=None, timeout_seconds=0, number_of_retries=0, cooldown_seconds = None):
        """
        The constructor of the ftp connection.
        Automatically logs in and changes the working directory to the ftp path.
        """
        # Making sure this is a positive number, or nothing at all.
        assert(number_of_retries >= 0 or number_of_retries == None)
        assert(timeout_seconds >= 0 or timeout_seconds == None)

        # Setting up.
        # TODO: "root_path" is probably a incorrect name. Should be renamed to something a bit more appropriate.
        self.host, self.root_path = FTP.split_ftp_host_and_path(ftp_remote_address)
        self.username = username
        self.password = password

        # Internally...
        self._number_of_retries = number_of_retries
        self._timeout_seconds = timeout_seconds
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_timestamp = None
        
        # Login.
        self.setup()

        LOG.debug("Changing remote path to %s."%(self.root_path))
        try:
            self.ftp.cwd(self.root_path)
        except ftplib.error_perm, e:
            LOG.error(e)
            LOG.error("Permission denied. Missing username/password?")
            raise e

    def setup(self):
        # Setting up timeout and so. This is where the work is done.
        @retry(self._number_of_retries)
        @timeout(self._timeout_seconds + self._cooldown_get_period())
        def _setup(self):
            LOG.debug("Setting up %s."%(self.host))
            self.ftp =  ftplib.FTP(self.host)
            LOG.debug("Logging in to %s."%(self.host))
            self.login()

        # Commanding the work done.
        try:
            _setup(self)
        except socket.error, e:
            LOG.error(e)
            LOG.error("Will sleep for 60 seconds and try again.")
            time.sleep(60)
            _setup(self)
            

    def _cooldown_get_period(self):
        if self._cooldown_timestamp:
            return int(time.mktime(datetime.datetime.now().timetuple())) - self._cooldown_timestamp
        return 0

    def _cooldown(self):
        """
        Internal method.
        If self._cooldown_seconds is set in the constructor, this ftp client, will cool down for the
        number of speficied seconds, since last request, before making a new request.

        E.g. a timestamp is set when the last download FINISHED.
        If self._cooldown_seconds is 3 and a new request is made after 2 seconds, the program will sleep
        for 1 second before the next download is made.
        """
        if self._cooldown_seconds:
            if self._cooldown_timestamp:
                time_since_last_action_seconds = self._cooldown_get_period()
                sleeptime_seconds = self._cooldown_seconds - time_since_last_action_seconds
                if sleeptime_seconds > 0:
                    LOG.debug("Cooling down for %i second(s)"%(sleeptime_seconds)) 
                    time.sleep(sleeptime_seconds )


    def _cooldown_set_timestamp(self):
        """
        Sets the timestamp used when cooling down.
        Only used if self._cooldown_seconds is specified.
        """
        if self._cooldown_seconds:
            LOG.debug("Setting cooldown timestamp.")
            self._cooldown_timestamp = int(time.mktime(datetime.datetime.now().timetuple()))

    def login(self, timeout_seconds = None):
        """
        Logs in to the ftp server.
        Using credentials if given.
        """
        # If timeout seconds is not an argument, use the default timeout.
        if not timeout_seconds:
            timeout_seconds = self._timeout_seconds

        @retry(self._number_of_retries)
        @timeout(timeout_seconds + self._cooldown_get_period() )
        def _login(self, LOG):
            """
            Internal function to log in to the ftp-server.
            Logs in to the ftp server.
            If specified, cools down first.
            Using credentials if given.
            """
            try:
                # Make sure the ftp variable is set up.
                if not hasattr(self, 'ftp') or not hasattr(self.ftp, 'socket'):
                    LOG.debug("No connection. Creating it.")
                    self._cooldown()
                    self.ftp = ftplib.FTP(self.host)
                    self._cooldown_set_timestamp()

                # Login
                self._cooldown()
                if self.username and self.password:
                    # ...with username.
                    LOG.debug("Logging in using credentials, %s."%(self.host))
                    self.ftp.login(self.username, self.password)
                else:
                    # ...without username.
                    LOG.debug("Logging in to the ftp server, %s."%(self.host))
                    self.ftp.login()

                # We are now logged in.
                LOG.debug("Logged in...")
                LOG.info(self.ftp.getwelcome())
            except Exception, e:
                # Make sure the exception/error gets registered.
                LOG.error(e)
                raise e
            finally:
                self._cooldown_set_timestamp()



        ## Execution.
        # Close down the ftp connection.
        LOG.debug("First trying to close the connection.")
        try: self.close()
        except: pass
        
        # Logging in.
        LOG.debug("Logging in.")
        _login(self, LOG)


    def download_file(self, remote_file_address, destination_filename, timeout_seconds=None):
        """
        This became more messy than expected... Have to go on for now...

        Downloading a file using ftplib. If fails, trying url2lib.
        Retrying if specified in the constructor.
        """
        LOG.info("\n")
        LOG.info("%s %s %s"%("*"*10, remote_file_address, "*"*10))

        if not timeout_seconds:
            timeout_seconds = self._timeout_seconds

        assert(timeout_seconds > 0)

        @retry(self._number_of_retries)
        @timeout(timeout_seconds + self._cooldown_get_period())
        def download_using_ftplib(self, remote_file_address, destination_filename, LOG):
            LOG.debug("Using ftplib: Downloading '%s' to '%s'."%(remote_file_address, destination_filename))
            destination_filename_tmp = "%s.tmp"%(destination_filename)
            LOG.debug("Tmp filename for '%s': '%s'."%(destination_filename, destination_filename_tmp) )
        
            # Make sure the temp file does not exist.
            if os.path.isfile(destination_filename_tmp):
                LOG.debug("The tmp destination file '%s' exists already. Deleting it.."%(destination_filename_tmp ))
                os.remove(destination_filename_tmp)

            # Download the file.

            self._cooldown()
            try:
                LOG.debug("Trying to download: '%s'."%(remote_file_address ))
                with open(destination_filename_tmp, 'wb') as local_file:
                    self.ftp.retrbinary("RETR %s"%(remote_file_address), local_file.write )
            except Exception, e:
                LOG.error("Failed downloading '%s'."%(remote_file_address ))
                LOG.error(e)
                # Exception is caught by the retry decorator.
                raise e
            finally:
                self._cooldown_set_timestamp()
            
            # Checking that the tmp filename has a size larger than 0.
            # If it does rename the tmp file to the destination filename.
            if os.path.isfile(destination_filename_tmp):
                if os.path.getsize(destination_filename_tmp) == 0:
                    LOG.warning("'%s' has size 0."%(destination_filename_tmp))
                else:
                    LOG.debug("Moving '%s' to '%s'."%(destination_filename_tmp, destination_filename))
                    shutil.move(destination_filename_tmp, destination_filename)
                    LOG.info("*"*50)
                    LOG.info("Ftplib: File '%s' saved."%(destination_filename))
                    LOG.info("*"*50)
                    LOG.info("")
                    return True
            LOG.warning("Failed to download '%s'."%(destination_filename_tmp))
            return False

        @retry(self._number_of_retries)
        @timeout(timeout_seconds + self._cooldown_get_period())
        def download_using_urllib2(self, remote_file_address, destination_filename, LOG):
            LOG.debug("Using urllib2: Downloading '%s' to '%s'."%(remote_file_address, destination_filename))
            LOG.debug("Building remote url...")
            if remote_file_address.startswith("ftp://"):
                # Removing the ftp://. Making it possible to put in username and password later on.
                remote_url = remote_file_address.replace("ftp://", "", 1)
            elif remote_file_address.startswith("/"):
                # The reslut of the below should be the same as removing the ftp:// string...
                remote_url = "%s%s"%(self.host, remote_file_address)
            else:
                # This should again be the same as removing the ftp:// string above...
                remote_url = "%s%s/%s"%(self.host, self.root_path, remote_file_address)
                
            # Adding username and password if specified.
            if self.username and self.password:
                remote_url = "%s:%s@%s"%(self.username, self.password, remote_url)

            # Putting the ftp:// string back in.
            remote_url = "ftp://%s"%(remote_url)

            # Temp destination filename
            destination_filename_tmp = "%s.tmp"%(destination_filename)
            LOG.debug("Tmp filename for '%s': '%s'."%(destination_filename, destination_filename_tmp) )

            # Downloading the file, using urllib2.
            LOG.debug("Downloading file, '%s' to '%s' using urllib2."%(remote_url, destination_filename_tmp))
            self._cooldown()
            try:
                with contextlib.closing(urllib2.urlopen(remote_url)) as remote_file:
                    LOG.debug("Remote file, %s, opened."%(remote_url))
                    with open(destination_filename_tmp, 'wb') as local_file:
                        LOG.debug("Local file: '%s'."%(destination_filename_tmp))
                        shutil.copyfileobj(remote_file, local_file)
                        LOG.debug("File '%s' saved."%(destination_filename_tmp) )
            except Exception, e:
                LOG.error(e)
                # Error is caught by the retry decorator.
                raise e
            finally:
                self._cooldown_set_timestamp()

            # Checking that the tmp filename has a size larger than 0.
            # If it does rename the tmp file to the destination filename.
            if os.path.isfile(destination_filename_tmp):
                if os.path.getsize(destination_filename_tmp) > 0:
                    LOG.debug("Moving '%s' to '%s'."%(destination_filename_tmp, destination_filename))
                    shutil.move(destination_filename_tmp, destination_filename)
                    LOG.info("*"*50)
                    LOG.info("Urllib2: File '%s' saved."%(destination_filename))
                    LOG.info("*"*50)
                    LOG.info("")
                    return True
                else:
                    LOG.warning("'%s' has size 0."%(destination_filename_tmp))
            LOG.warning("Failed to download '%s'."%(destination_filename_tmp))
            return False
        # Setup ends.

        try:
            if download_using_urllib2(self, remote_file_address, destination_filename, LOG):
                return True
        except Exception, e:
            LOG.error("Failed downloading using urllib2: %s"%(str(e)))
            LOG.error("Will try with ftplib.")
            
        # Commanding the work done!!!
        if not hasattr(self, 'ftp') or self.ftp == None:
            self.setup()

        try: 
            if download_using_ftplib(self, remote_file_address, destination_filename, LOG):
                return True
        except socket.error, e:
            # If the error is a socket error, the retry decorator will not retry, because the connection
            # most likely need to be reestablished. Therefore, recursively, retry to download the file, which 
            # includes setting up the connection again.
            try:
                LOG.debug("Sleeping for %i seconds."%(timeout_seconds * 5))
                time.sleep(timeout_seconds * 5)
                LOG.debug("Recursively trying to download the file.")
                return self.download_file(remote_file_address, destination_filename, timeout_seconds=timeout_seconds)
            except Exception, e:
                # We end up here, if the exception is not a socket.error. Else, retry recursively.
                raise e
        except Exception, e:
            LOG.error(e)
            LOG.error("Failed downloading '%s' using ftplib."%(remote_file_address))

        LOG.warning("*"*50)
        LOG.error("FAILED: Downloading '%s' failed permanentely."%(remote_file_address))
        LOG.error("Moving on.")
        LOG.warning("*"*50)
        return False


    @staticmethod
    def split_ftp_host_and_path(ftp_remote_address):
        """
        Splits the ftp address into host and path.
        
        What it does is remove the "ftp://" in the beginning of the address, and
        then split the string on the first "/", and then add "/" to the last part,
        to make it clear that it is the root path on the host.
        """

        if ftp_remote_address.startswith("ftp://"):
            LOG.debug("Removing ftp:// from remote address.")
            ftp_remote_address = ftp_remote_address.replace("ftp://", "", 1)
        LOG.debug(ftp_remote_address)

        if "/" in ftp_remote_address:
            remote_host, root_path = ftp_remote_address.split("/", 1)
        else:
            remote_host = ftp_remote_address
            root_path = "/"

        LOG.debug("Remote address, '%s', splitted into '%s' and '%s'."%(ftp_remote_address, remote_host, root_path))

        if not root_path.startswith("/"):
            root_path = "/%s"%(root_path)
        LOG.debug("Making sure the remote root path allways is absolute, '%s'."%(root_path))
        return remote_host, root_path

    def __enter__(self):
        """
        This function is called when using with statements.

        Example::
            with FTP(<ftp_address>) as ftp:
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
    
    def close(self):
        """
        Tries to close the ftp connection in a polite way.
        """
        # Only do it if it is there.
        if hasattr(self, 'ftp') and self.ftp != None:
            # try:
            # LOG.debug("Aborting.")
            # self.ftp.abort()
            # except Exception, e:
            #  LOG.warning(e)
            #  LOG.warning(sys.exc_info()[0])

            try:
                LOG.debug("Quitting.")
                self.ftp.quit()
            except Exception, e:
                LOG.warning(e)
                LOG.warning(sys.exc_info()[0])

            try:
                LOG.debug("Closing.")
                self.ftp.close()
                LOG.debug("FTP connection closed.")
            except Exception, e: 
                LOG.warning(e)
                LOG.warning(sys.exc_info()[0])

    def get_directories(self, path=None, timeout_seconds = None):
        """
        Gets a list of directories for a specific path. If path is not given,
        the directories in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with("d", path, timeout_seconds = timeout_seconds)

    def get_filenames(self, path=None, timeout_seconds = None):
        """
        Gets a list of files for a specific path. If path is not given,
        the files in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with("-", path, timeout_seconds = timeout_seconds)

    def get_links(self, path=None, timeout_seconds = None):
        """
        Gets a list of links for a specific path. If path is not given,
        the links in the root path of the full ftp address is returned.
        """
        return self.get_entries_starting_with("l", path, timeout_seconds = timeout_seconds)

    def get_entries_starting_with(self, startswith, path = None, timeout_seconds = None):
        """
        Parses the list content string and returns a list of all the entries starting with
        "startswith".
        """

        entries = []
        contents = self.list_contents(path, timeout_seconds=timeout_seconds)
        for content in contents:
            # TODO: Return an object containing some more information about the files / directories / links.
            # There is more info in the string, which e.g. could be parsed into an object.
            if content.startswith(startswith):
                # content e.g.: drwxrwxr-x    2 12546    101        159744 Mar 13 21:51 2012.354
                entries.append(content.split(" ")[-1])
        return entries

    def list_contents(self, path=None, timeout_seconds = None):
        """
        Lists the contents for a given path.
        When the contents has been listed, the working directory is 
        Retries once if an error occurs.
        """
        if not timeout_seconds:
            timeout_seconds = self._timeout_seconds

        @retry(self._number_of_retries)
        @timeout(timeout_seconds + self._cooldown_get_period())
        def _list_contents(self, path=None):
            """
            Changes the directory to the path, if given, and list all the contents in that directory. Then automatically
            changes the working directory back to the ftp address root.
            
            Returns a list of lines that the ftp server returns.
            """
            self._cooldown()
            try:
                # Make sure we are logged in.
                self.setup()

                prev_working_dir = None
                if path:
                    prev_working_dir = self.ftp.pwd()
                    LOG.debug("Working dir: '%s'."%(prev_working_dir))

                    LOG.debug("Changing path to %s"%(path))
                    self.ftp.cwd(path)
                contents = []
                self.ftp.retrlines("LIST", contents.append)
                return contents
            finally:
                if prev_working_dir != None:
                    LOG.debug("Changing back to previous working dir: '%s'."%(prev_working_dir))
                    self.ftp.cwd(prev_working_dir)
                self._cooldown_set_timestamp()


        try:
            return _list_contents(self, path)
        except socket.error, e:
            # Most likely because the session has timed out, or something alike.
            # The solution seem to be to relogin.
            LOG.error("Failed listing contentes. Retrying.")
            LOG.error(e)
            LOG.error("Trying to log in again.")
            self.login()
            
            LOG.error("Trying to list contents again.")
            return _list_contents(self, path)



        

if __name__ == "__main__":
    try:
        import argparse
    except Exception, e:
        print ""
        print "Try running 'sudo apt-get install python-argparse' or 'sudo easy_install argparse'!!"
        print ""
        raise e

    def string2date(date_string):
        return datetime.datetime.strptime(date_string, '%Y-%m-%d').date()

    def directory(dir_path):
        if not os.path.isdir(dir_path):
            raise argparse.ArgumentTypeError("'%s' does not exist. Please specify save directory!"%(dir_path))
        return dir_path

    parser = argparse.ArgumentParser(description='Connect to an ftp server and list the files, directories and links in the directory.')
    parser.add_argument("remote_source_address"
                         , type=str
                         , help='Remote source adress, e.g. ftp://example.com/some/nice/path'
                        )
    parser.add_argument('-u', '--username'
                         , type=str
                         , help='Some directory, that exists, if set (optional)...'
                        )
    parser.add_argument('-p', '--password'
                         , type=str
                         , help="Some string."
                        )
    parser.add_argument('-d', '--debug', action='store_true', help="Output debugging information.")
    parser.add_argument('--log_filename', type=str, help="File used to output logging information.")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(filename=args.log_filename, level=logging.DEBUG)
    else:
        logging.basicConfig(filename=args.log_filename, level=logging.INFO)

    if args.username and not args.password:
        raise argparse.ArgumentTypeError("Both username and password must be set")
    
    # Output what is in the args variable.
    LOG.debug(args)

    with FTP(args.remote_source_address, args.username, args.password) as ftp:
        directories = ftp.get_directories()
        files = ftp.get_filenames()
        links = ftp.get_links()

        print "Remote root directory:", ftp.root_path
        print "Number of directories:", len(directories)
        print "Number of files:", len(files)
        print "Number of links:", len(links)
