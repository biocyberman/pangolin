#!/usr/bin/env python3
from pangolin import __version__
import argparse
import os.path
import snakemake
import sys
from tempfile import gettempdir
import tempfile
import pprint
import json
import os
import joblib
import lineages
import pangoLEARN

import pkg_resources
from Bio import SeqIO


from . import _program


thisdir = os.path.abspath(os.path.dirname(__file__))
cwd = os.getcwd()

def main(sysargs = sys.argv[1:]):

    parser = argparse.ArgumentParser(prog = _program, 
    description='pangolin: Phylogenetic Assignment of Named Global Outbreak LINeages', 
    usage='''pangolin <query> [options]''')

    parser.add_argument('query', help='Query fasta file of sequences to analyse.')
    parser.add_argument('-o','--outdir', action="store",help="Output directory. Default: current working directory")
    parser.add_argument('--outfile', action="store",help="Optional output file name. Default: lineage_report.csv")
    parser.add_argument('-d', '--data', action='store',help="Data directory minimally containing a fasta alignment and guide tree")
    parser.add_argument('-n', '--dry-run', action='store_true',help="Go through the motions but don't actually run")
    parser.add_argument('--tempdir',action="store",help="Specify where you want the temp stuff to go. Default: $TMPDIR")
    parser.add_argument("--no-temp",action="store_true",help="Output all intermediate files, for dev purposes.")
    parser.add_argument('--max-ambig', action="store", default=0.5, type=float,help="Maximum proportion of Ns allowed for pangolin to attempt assignment. Default: 0.5",dest="maxambig")
    parser.add_argument('--min-length', action="store", default=10000, type=int,help="Minimum query length allowed for pangolin to attempt assignment. Default: 10000",dest="minlen")
    parser.add_argument('--panGUIlin', action='store_true',help="Run web-app version of pangolin",dest="panGUIlin")
    parser.add_argument('--legacy',action='store_true',help="LEGACY: Use original phylogenetic assignment methods with guide tree. Note, will be significantly slower than pangoLEARN")
    parser.add_argument('--write-tree', action='store_true',help="Output a phylogeny for each query sequence placed in the guide tree. Only works in combination with legacy `--assign-using-tree`",dest="write_tree")
    parser.add_argument('-t', '--threads', action='store',type=int,help="Number of threads")
    parser.add_argument("-p","--include-putative",action="store_true",help="Include the bleeding edge lineage definitions in assignment",dest="include_putative")
    parser.add_argument("--verbose",action="store_true",help="Print lots of stuff to screen")
    parser.add_argument("-v","--version", action='version', version=f"pangolin {__version__}")
    parser.add_argument("-lv","--lineages-version", action='version', version=f"lineages {lineages.__version__}",help="show lineages's version number and exit")
    parser.add_argument("-pv","--pangoLEARN-version", action='version', version=f"pangoLEARN {pangoLEARN.__version__}",help="show pangoLEARN's version number and exit")

    if len(sysargs)<1:
        parser.print_help()
        sys.exit(-1)
    else:
        args = parser.parse_args(sysargs)

    if args.legacy:
        snakefile = os.path.join(thisdir, 'scripts','Snakefile')
    # find the Snakefile
    else:
        snakefile = os.path.join(thisdir, 'scripts','pangolearn.smk')
    if not os.path.exists(snakefile):
        sys.stderr.write('Error: cannot find Snakefile at {}\n'.format(snakefile))
        sys.exit(-1)
    else:
        print("Found the snakefile")

    # find the query fasta
    query = os.path.join(cwd, args.query)
    if not os.path.exists(query):
        sys.stderr.write('Error: cannot find query (input) fasta file at {}\nPlease enter your fasta sequence file and refer to pangolin usage at:\nhttps://github.com/hCoV-2019/pangolin#usage\n for detailed instructions\n'.format(query))
        sys.exit(-1)
    else:
        print(f"The query file is {query}")

        # default output dir
    outdir = ''
    if args.outdir:
        outdir = os.path.join(cwd, args.outdir)
        if not os.path.exists(outdir):
            try:
                os.mkdir(outdir)
            except:
                sys.stderr.write(f'Error: cannot create directory {outdir}')
                sys.exit(-1)
    else:
        outdir = cwd

    outfile = ""
    if args.outfile:
        outfile = os.path.join(outdir, args.outfile)
    else:
        outfile = os.path.join(outdir, "lineage_report.csv")

    tempdir = ''
    if args.tempdir:
        to_be_dir = os.path.join(cwd, args.tempdir)
        if not os.path.exists(to_be_dir):
            os.mkdir(to_be_dir)
        temporary_directory = tempfile.TemporaryDirectory(suffix=None, prefix=None, dir=to_be_dir)
        tempdir = temporary_directory.name
    else:
        temporary_directory = tempfile.TemporaryDirectory(suffix=None, prefix=None, dir=None)
        tempdir = temporary_directory.name
    
    if args.no_temp:
        print(f"--no-temp: All intermediate files will be written to {outdir}")
        tempdir = outdir

    """ 
    QC steps:
    1) check no empty seqs
    2) check N content
    3) write a file that contains just the seqs to run
    """

    do_not_run = []
    run = []
    for record in SeqIO.parse(query, "fasta"):
        # replace spaces in sequence headers with underscores
        record.id = record.description.replace(' ', '_')
        if "," in record.id:
            record.id=record.id.replace(",","_")

        if len(record) <args.minlen:
            record.description = record.description + f" fail=seq_len:{len(record)}"
            do_not_run.append(record)
            print(record.id, "\tsequence too short")
        else:
            num_N = str(record.seq).upper().count("N")
            prop_N = round((num_N)/len(record.seq), 2)
            if prop_N > args.maxambig: 
                record.description = record.description + f" fail=N_content:{prop_N}"
                do_not_run.append(record)
                print(f"{record.id}\thas an N content of {prop_N}")
            else:
                run.append(record)

    if not args.legacy:
        if run == []:
            with open(outfile, "w") as fw:
                fw.write("taxon,lineage,probability,pangoLEARN_version,status,note\n")
                for record in do_not_run:
                    desc = record.description.split(" ")
                    reason = ""
                    for item in desc:
                        if item.startswith("fail="):
                            reason = item.split("=")[1]
                    fw.write(f"{record.id},None,0,{pangoLEARN.__version__},fail,{reason}\n")
            print(f'Note: no query sequences have passed the qc\n')
            sys.exit(0)
            
    post_qc_query = os.path.join(tempdir, 'query.post_qc.fasta')
    with open(post_qc_query,"w") as fw:
        SeqIO.write(run, fw, "fasta")
    qc_fail = os.path.join(tempdir,'query.failed_qc.fasta')
    with open(qc_fail,"w") as fw:
        SeqIO.write(do_not_run, fw, "fasta")

    # how many threads to pass
    if args.threads:
        threads = args.threads
    else:
        threads = 1

    print("Number of threads is", threads)

    config = {
        "query_fasta":post_qc_query,
        "outdir":outdir,
        "outfile":outfile,
        "tempdir":tempdir,
        "trim_start":265,   # where to pad to using datafunk
        "trim_end":29674,   # where to pad after using datafunk
        "qc_fail":qc_fail,
        "lineages_version":lineages.__version__,
        "pangoLEARN_version":pangoLEARN.__version__,
        "compressed_model_size": 569253
        }

    # find the data
    data_dir = ""
    if args.data:
        data_dir = os.path.join(cwd, args.data)

    if args.legacy:
        if not args.data:
            lineages_dir = lineages.__path__[0]
            data_dir = os.path.join(lineages_dir,"data")

        representative_aln = ""
        guide_tree = ""
        lineages_csv = ""

        for r,d,f in os.walk(data_dir):
            for fn in f:
                if args.include_putative:
                    if fn.endswith("putative.fasta"):
                        representative_aln = os.path.join(r, fn)
                    elif fn.endswith("putative.fasta.treefile"):
                        guide_tree = os.path.join(r, fn)
                    elif fn.endswith(".csv") and fn.startswith("lineages"):
                        lineages_csv = os.path.join(r, fn)
                else:
                    if fn.endswith("safe.fasta"):
                        representative_aln = os.path.join(r, fn)
                    elif fn.endswith("safe.fasta.treefile"):
                        guide_tree = os.path.join(r, fn)
                    elif fn.endswith(".csv") and fn.startswith("lineages"):
                        lineages_csv = os.path.join(r, fn)

        
        if representative_aln=="" or guide_tree=="" or lineages_csv=="":
            print("""Check your environment, didn't find appropriate files from the lineages repo, please see https://cov-lineages.org/pangolin.html for installation instructions. \nTreefile must end with `.treefile`.\
\nAlignment must be in `.fasta` format.\n Trained model must exist. \
If you've specified --include-putative\n \
you must have files ending in putative.fasta.treefile\nExiting.""")
            exit(1)
        else:
            print("\nData files found")
            print(f"Sequence alignment:\t{representative_aln}")
            print(f"Guide tree:\t\t{guide_tree}")
            print(f"Lineages csv:\t\t{lineages_csv}")
            config["representative_aln"]=representative_aln
            config["guide_tree"]=guide_tree

    else:
        if not args.data:
            pangoLEARN_dir = pangoLEARN.__path__[0]
            data_dir = os.path.join(pangoLEARN_dir,"data")
        print(f"Looking in {data_dir} for data files...")
        trained_model = ""
        header_file = ""
        lineages_csv = ""

        for r,d,f in os.walk(data_dir):
            for fn in f:
                if fn == "decisionTreeHeaders_v1.joblib":
                    header_file = os.path.join(r, fn)
                elif fn == "decisionTree_v1.joblib":
                    trained_model = os.path.join(r, fn)
                elif fn == "lineages.metadata.csv":
                    lineages_csv = os.path.join(r, fn)
        if trained_model=="" or header_file==""  or lineages_csv=="":
            print("""Check your environment, didn't find appropriate files from the pangoLEARN repo.\n Trained model must be installed, please see https://cov-lineages.org/pangolin.html for installation instructions.""")
            exit(1)
        else:
            if("compressed_model_size" in config):
                if os.path.getsize(trained_model) <= config["compressed_model_size"] + 10:
                    print("Decompressing model and header files")
                    model = joblib.load(trained_model)
                    headers = joblib.load(header_file)
                    trained_model = os.path.join(tempdir, os.path.basename(trained_model))
                    header_file = os.path.join(tempdir, os.path.basename(header_file))
                    joblib.dump(model, trained_model, compress=0)
                    joblib.dump(headers, header_file, compress=0)

            print("\nData files found")
            print(f"Trained model:\t{trained_model}")
            print(f"Header file:\t{header_file}")
            print(f"Lineages csv:\t{lineages_csv}")
            config["trained_model"] = trained_model
            config["header_file"] = header_file

    reference_fasta = pkg_resources.resource_filename('pangolin', 'data/reference.fasta')
    config["reference_fasta"] = reference_fasta

    variants_file = pkg_resources.resource_filename('pangolin', 'data/config_b.1.1.7.csv')
    config["b117_variants"] = variants_file
    
    variants_file = pkg_resources.resource_filename('pangolin', 'data/config_b.1.351.csv')
    config["b1351_variants"] = variants_file

    variants_file = pkg_resources.resource_filename('pangolin', 'data/config_p.1.csv')
    config["p1_variants"] = variants_file

    variants_file = pkg_resources.resource_filename('pangolin', 'data/config_p.2.csv')
    config["p2_variants"] = variants_file
    
    if args.write_tree:
        config["write_tree"]="True"

    if args.panGUIlin:
        config["lineages_csv"]=lineages_csv


    if args.verbose:
        quiet_mode = False
    else:
        quiet_mode = True

    # run subtyping
    status = snakemake.snakemake(snakefile, printshellcmds=True,
                                 dryrun=args.dry_run, forceall=True,force_incomplete=True,
                                 config=config, cores=threads,lock=False,quiet=quiet_mode,workdir=tempdir
                                 )

    if status: # translate "success" into shell exit code of 0
       return 0

    return 1

if __name__ == '__main__':
    main()
