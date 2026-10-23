#!/bin/sh
# Copy the report to the shop's server and restart it.
set -e

TARGET=$1
DEST_DIR=/srv/shopkit
STAMP=$(date +%Y%m%d-%H%M)
ARCHIVE=shopkit-$STAMP.tar.gz

if [ -z $TARGET ]; then
    echo "usage: deploy.sh HOST"
    exit 2
fi

tar czf $ARCHIVE shopkit app.py config.json
scp $ARCHIVE $TARGET:/tmp/
ssh $TARGET "mkdir -p $DEST_DIR && tar xzf /tmp/$ARCHIVE -C $DEST_DIR"
ssh $TARGET "systemctl --user restart shopkit"
rm $ARCHIVE
echo "deployed $ARCHIVE to $TARGET"
