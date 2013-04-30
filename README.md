python-easy-ftp
===============

Make it easier to access ftp server content from python.

WARNING:
--------
The code has not really been tested!

HOW TO USE
----------
Code example::

    import easy_ftp
    
    with easy_ftp.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        directories = ftp.get_directories()
        files = ftp.get_filenames()
        links = ftp.get_links()
        
        if ftp.download_file( "/<some dir path>/<filename>", destination_filename ):
            print "Files was downloaded."
        else:
            print "File was not downloaded."

When downloading files, both relative and absolute paths can be used. E.g. both should work::

    import easy_ftp
     
    with easy_ftp.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
        ftp.download_file( "/ftp/root/path/fish.txt", destination_filename ):
        ftp.download_file( "fish.txt", destination_filename ):
     
Also, these should be the same::

    import easy_ftp

    with easy_ftp.FtpConnection( "ftp://<ftp host name>/ftp/root/path" ) as ftp:
    	 filenames_1 = ftp.get_filenames( "/ftp/root/path/with/fish/file/" )
         filenames_2 = ftp.get_filenames( "with/fish/file/" )


TODO list
---------
A lot needs to be done. Some of the most obvious are:

- Add file sizes from remote files / directories / links.
- Add other file attributes to the files / directories / links.
- Add the possibility to navigate within the ftp directories. A suggestion could be to implement a os.walk() like method.
- Using yield in stead of adding to a list and return it.
- Downloading whole directories at once.
- Add more here...
- Add even more here
- Do it!! Do it!!
