#!/bin/bash
mkdir -p /ramdisk
chmod 777 /ramdisk
rm -rf /ramdisk/*
python3 -m bot
