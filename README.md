python-easy-ftp
===============

Make it easier to access ftp server content from python.

HOW TO USE
----------
Code example::

       import ftp_connection

       with ftp_connection.FtpConnection( "ftp://<ftp host name>/<ftp root path>" ) as ftp:
       	    files = ftp.get_filenames()
	    directories = ftp.get_directories( )
	    links = ftp.get_links()

	    if ftp.download_file( "/<some dir path>/<filename>", destination_filename ):
	       print "Files was downloaded."
	    else:
	       print "File was not downloaded."


TODO list
---------
At lot need to be done, but some of the most obvious is:

- Add file sizes from remote files / directories / links.
- Add other file attributes to the files / directories / links.
- Add the possibility to navigate within the ftp directories.
- Downloading whole directories at once.
- <Add more here...>
- <Add even more here>
- <Do it!! Do it!!>
