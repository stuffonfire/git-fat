#!/usr/bin/env perl

$prefix = "";

# open(, "<binary.dat");
read(STDIN, $prefix, 12, 0);

if ( $prefix eq '#$# git-fat '){
    read(STDIN, $fname, 40,0);
    
    sub  trim { my $s = shift; $s =~ s/^\s+|\s+$//g; return $s };
    $gitdir = $ENV{'GIT_DIR'} or trim( `git rev-parse --git-dir` );
    $fpath = "$gitdir/fat/objects/$fname";
    if ( -f $fpath){
        open($fh, "<", $fpath);
        binmode($fh);
        while ( read( $fh, $buf, 4096,0) ){
            print($buf);
        }
        
    }else{
        print( $prefix );
        print( $fname );
        while ( read( STDIN, $buf, 4096,0) ){
            print($buf);
        }
    }
    
}else{
    print( $prefix );
    while ( read( STDIN, $buf, 4096,0) ){
        print($buf);
    }
}
