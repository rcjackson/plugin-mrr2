import serial
import time
import argparse
import xarray as xr
import tempfile
import subprocess
import threading
import glob
import os
import shutil

from waggle.plugin import Plugin
from datetime import datetime, timezone, timedelta


def parse_mrr_signal(serial, plugin):
    """
    This parses the incoming signal from the MRR and writes the data to a file for
    processing by IMProToo.

    Parameters
    ----------
    serial: PySerial serial connection
        The serial connection to pull from.
    plugin: Plugin instance
        The plugin instance.
    out_file: file handle
        The output file handle to write to.
    """
    # Hex 01 is the start of an MRR record
    # Hex 02 is the start of a raw spectra line
    # Beginning of record, need to add the UTC date and time and MRR
    record_started = False
    exit = False
    out_file = None
    while exit == False:
        try:
            line = serial.readline()
        except pyserial.SerialException:
            continue
        if line.startswith(b'\x01'):
            cur_time = datetime.now(timezone.utc)
            time_str = datetime.strftime(cur_time, "%y%m%d%H%M%S")
            if out_file is None:
                out_file_name = '%s.raw' % time_str
                out_file = open(out_file_name, 'w')
            out_line = "MRR %s UTC " % time_str + line[2:-5].decode("utf-8") + "\n"
            out_file.write(out_line)
            record_started = True
            print("Start MRR record %s" % time_str)
        # Line in middle of record    
        if line.startswith(b'\x02') and record_started:
            out_file.write(line[1:-5].decode("utf-8") + "\n")
        # End of record, if we have record written then close.
        if line.startswith(b'\x04'):
            if record_started:
            # Write new record every 5 minutes    
                if cur_time.minute == 0 and cur_time.second < 10:
                    out_file.close()
                    out_file = None
                    print(out_file_name)
                    plugin.upload_file(out_file_name, keep=True)
                    shutil.move(out_file_name, '/app/raw_files/' + out_file_name)
                    exit = True


def process_hour(plugin):
    cur_time = datetime.now()
    previous_hour = cur_time - timedelta(hours=1)
    wildcard = '/app/raw_files/%s*.raw' % datetime.strftime(previous_hour, "%y%m%d%H")
    fname_str = 'mrr2atmos.%s0000.nc' % datetime.strftime(previous_hour,
                                '%Y%m%d_%H')
    subprocess.run(["python3", "RaProM_38.py", fname_str])
    plugin.upload_file('/app/raw_files/' + fname_str)
    for fi in glob.glob(wildcard):
        os.remove(fi)
    print("Published %s" % fname_str)


def main(args):
    if not os.path.exists('/app/raw_files/'):
        os.makedirs('/app/raw_files/')
    with serial.Serial(
            args.device, 57600, parity=serial.PARITY_NONE,
            xonxoff=True, timeout=args.timeout) as ser:
        print("Serial connection to %s open" % args.device)
        thread = None
        with Plugin() as plugin:
            published_this_hour = False
            while True:    
                parse_mrr_signal(ser, plugin)
                cur_time = datetime.now()
                if cur_time.minute == 0:
                    if published_this_hour == False:
                        published_this_hour = True
                        thread = threading.Thread(target=process_hour, args=(plugin,))
                        thread.start()
                else:
                     published_this_hour = False
                


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
            description="Plugin for transferring the MRR-2 data.")
    parser.add_argument("--device",
            type=str,
            dest='device',
            default='/dev/ttyUSB1',
            help='serial device to use')
    parser.add_argument("--timeout",
            type=float,
            dest='timeout',
            default=1,
            help="Number of seconds before signal timeout.")
    args = parser.parse_args()
    main(args)