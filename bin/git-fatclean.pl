#!/usr/bin/env perl

$prefix = "";



# open(, "<binary.dat");
read(STDIN, $prefix, 12, 0);

if ( $prefix eq '#$# git-fat '){
   print($prefix);
   while ( read( STDIN, $buf, 4096,0) ){
      print($buf);
   }   
}else{

    use File::Temp qw/ tempfile /;
    use File::Copy;

    ($temp_fh, $temp_filename) = tempfile();

    $bytes_read = length($prefix);
    use Digest::SHA1;
    
    $sha1 = Digest::SHA1->new;
    $sha1->add($prefix);

    # is this supposed to be here?
    print $temp_fh $buf

    while ( $br = read( STDIN, $buf, 4096,0) ){
        $sha1->add($buf);
        $bytes_read += $br;
        print $temp_fh $buf;
    }
    close($temp_fh);

    $digest = $sha1->hexdigest
    print('#$# git-fat ');
    print($digest);
    print(' ');
    printf("%20d\n", $bytes_read);

    sub  trim { my $s = shift; $s =~ s/^\s+|\s+$//g; return $s };
    $gitdir = $ENV{'GIT_DIR'} or trim( `git rev-parse --git-dir` );
    $fpath = "$gitdir/fat/objects/$digest";
    if ( ! -f $fpath ){
        move( $temp_filename, $fpath );
    }else{
        unlink $temp_filename;
    }

}
