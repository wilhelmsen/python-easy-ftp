python-easy-ftp
===============

Make it easier to access ftp server content from python.

HOW TO USE
----------
Code example::

    import ftp_connection
    
    with ftp_connection.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        directories = ftp.get_directories()
        files = ftp.get_filenames()
        links = ftp.get_links()
        
        if ftp.download_file( "/<some dir path>/<filename>", destination_filename ):
            print "Files was downloaded."
        else:
            print "File was not downloaded."

When downloading files, both relative and absolute paths can be used. E.g. both should work::
     
    with ftp_connection.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        ftp.download_file( "/ftp/root/path/fish.txt", destination_filename ):
        ftp.download_file( "fish.txt", destination_filename ):
     
Also, these should be the same:
    with ftp_connection.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        ftp.get_filenames( "/ftp/root/path/with/fish/file/" )
        ftp.get_filenames( "with/fish/file/" )


TODO list
---------
At lot need to be done, but some of the most obvious is:

- Add file sizes from remote files / directories / links.
- Add other file attributes to the files / directories / links.
- Add the possibility to navigate within the ftp directories. A suggestion could be to implement a os.walk() like method.
- Using yield in stead of adding to a list and return it.
- Downloading whole directories at once.
- Add more here...
- Add even more here
- Do it!! Do it!!
