#!/usr/bin/python -u

import os
import re
import math
import ConfigParser

import MySQLdb
import MySQLdb.cursors

from optparse import OptionParser, SUPPRESS_HELP

#
def map_position(domain, substitution):
    """
    return the corresponding position within a HMM (for a given amino 
    acid position)
    """
    
    # return if the amino acid substitution falls outside of the domain 
    # assignment 
    if int(substitution[1:-1]) < int(domain['seq_start']) or \
       int(substitution[1:-1]) > int(domain['seq_end']):
        return None
    
    # adjust the sequence/HMM position (Python has zero-based coordinates)
    x = int(domain['seq_start']) - 1 
    y = int(domain['hmm_start']) - 1 
    
    # map amino acid substitution onto the HMM
    for residue in list(domain['alignment']):
        if residue.isupper() or residue.islower():
            # upper-case (match)/lower-case (insertion) characters map 
            # onto a sequence residue
            x += 1
        if residue.isupper() or residue == "-":
            # upper-case (match)/gap (deletion) characters map onto a
            # HMM position
            y += 1
        if x == int(substitution[1:-1]):
            if residue.isupper():
                # return corresponding position within the HMM
                return str(y)
            # unmapped residue (i.e. insertion)
            return None
    return None

#
def fetch_prediction(facade, substitution):
    """
    return a prediction score, according to the requested algorithm, 
    alongside domain-phenotype associations
    """
    
    Score      = None
    Phenotypes = []
    
    # use the most informative Facade record ...
    for x in sorted(facade, key=lambda x:x['information'], reverse=True):
        if not Score:
            if options.weights.upper() == "UNWEIGHTED":
                # derive an "Unweighted Prediction" ...
                p     = x[substitution[0]]
                q     = x[substitution[-1]]
                
                Score = "%.2f" % math.log((q / (1.0 - q)) / (p / (1.0 - p)), 2)
            else:
                # derive a "Weighted" prediction depending on the selected
                # pathogenicity weights ...
                dbCursor.execute("select * from Weights where id='" + x['id'] + "' and type='" + options.weights + "'")
                Weights   = dbCursor.fetchone()

                if Weights:
                    p     = x[substitution[0]]
                    q     = x[substitution[-1]]
                    r     = Weights['polymorphic']
                    s     = Weights['pathogenic']
                    
                    Score = "%.2f" % math.log(((1.0 - p) * (r + 1.0)) / ((1.0 - q) * (s + 1.0)), 2)
        
        # derive domain-phenotype associations (via the most informative
        # SUPERFAMILY HMM)
        if not Phenotypes and x['accession']:
            dbCursor.execute("select * from Phenotypes where accession='" + x['accession'] + "' and ontology='" + options.phenotypes + "' and origin=1 order by score")
            Phenotypes = dbCursor.fetchall()
            
        if Score and Phenotypes:
            # prediction(s) have been made ...
            break
    
    return (Score, Phenotypes)
            
#
def process_record(dbSNP, protein, substitution):
    """
    
    """
    
    # fetch pre-computed sequence record
    dbCursor.execute("select a.* from Clusters a, Protein b where a.id=b.cluster and b.name='" + protein + "'")
    SeqRecord = dbCursor.fetchone()
    
    if not SeqRecord:
        # no pre-computed sequence record
        Predictions.write(
            "\t".join([ str(idx), dbSNP, protein, substitution, "", "", "", "No Sequence Record Found" ]) + "\n"
        ); return False
    
    # authenticate protein/substitution
    Warning     = None
    
    if not Warning and not re.compile("^[ARNDCEQGHILKMFPSTWYV]\d+[ARNDCEQGHILKMFPSTWYV]$", re.IGNORECASE).match(substitution):
        # authenticate substitution format
        Warning = "Invalid Substitution Format"
    if not Warning and int(substitution[1:-1]) > SeqRecord['sequence'].__len__():
        # authenticate substitution position
        Warning = "Invalid Substitution Position"
    if not Warning and not substitution[0] == SeqRecord['sequence'][int(substitution[1:-1]) - 1]:
        # authenticate substitution residue(s)
        Warning = "Inconsistent Wild-Type Residue (Expected '" + SeqRecord['sequence'][int(substitution[1:-1]) - 1] + "')"
    if not Warning and substitution[0] == substitution[-1]:
        # authenticate substitution type
        Warning = "Synonymous Mutation"
    if  Warning:
        # return the corresponding warning
        Predictions.write(
            "\t".join([ str(idx), dbSNP, protein, substitution, "", "", "", Warning ]) + "\n"
        ); return False
    
    # create a facade of possible prediction(s)
    Facade    = []
    
    # fetch substitution-harbouring protein domains
    dbCursor.execute("select * from Domains where id='" + SeqRecord['id'] + "' and " + substitution[1:-1] + " between seq_start and seq_end order by evalue")
    DomRecord = dbCursor.fetchall()
    
    for x in DomRecord:
        # fetch the corresponding position within the HMMs
        residue = map_position(x, substitution)
            
        if residue:
            # fetch description/probabilities for mapped position
            dbCursor.execute("select a.*, b.accession, b.description from Probabilities a, Library b where a.id=b.id and a.id='" + str(x['hmm']) + "' and a.position='" + residue + "'")
            dbRecord = dbCursor.fetchone()
            
            if dbRecord:
                # append as a possible prediction
                Facade.append(dbRecord)
    
    # derive a prediction based on the most informative HMM
    if options.weights.upper() == "UNWEIGHTED":
        # if "Unweighted" prediction", append JackHMMER probabilities/conservation ...
        dbCursor.execute("select a.*, b.accession, b.description from Probabilities a, Library b where a.id=b.id and a.id='" + SeqRecord['id'] + "' and a.position='" + substitution[1:-1] + "'")
        ConRecord = dbCursor.fetchone()
        
        if ConRecord:
            # append as a possible prediction
            Facade.append(ConRecord)
        
        # fetch prediction(s) ...
        (Score, Phenotypes) = fetch_prediction(Facade, substitution)
    else:
        # ... otherwise, prioritize domain-centric predictions i.e. use 
        # JackHMMER probabilities/conservation when no domain-centric 
        # predictions have been made
        (Score, Phenotypes) = fetch_prediction(Facade, substitution)
        
        if not Score:
            # append JackHMMER probabilities/conservation
            dbCursor.execute("select a.*, b.accession, b.description from Probabilities a, Library b where a.id=b.id and a.id='" + SeqRecord['id'] + "' and a.position='" + substitution[1:-1] + "'")
            ConRecord = dbCursor.fetchone()
            
            if ConRecord:
                # append as a possible prediction
                Facade.append(ConRecord)
            
            # fetch prediction(s) ...
            (Score, Phenotypes) = fetch_prediction(Facade, substitution)
        
    # write our prediction
    if not Score:
        # no pathogenicity weights/prediction score
        Predictions.write(
            "\t".join([ str(idx), dbSNP, protein, substitution, "", "", "", "No Prediction Available" ]) + "\n"
        ); return False
    
    if not options.weights.upper() == "UNWEIGHTED":
        if options.weights.upper() == "INHERITED":
            # "Inherited Disease" predictions ...
            Tag = "TOLERATED"
            
            if float(Score) < -1.50:
                Tag = "DAMAGING" 
        else:
            # "Cancer-Associated" predictions ...
            Tag = "PASSENGER/OTHER"
        
            if float(Score) < -1.00:
                Tag = "CANCER" 
    else:
        Tag = "TOLERATED"
        
        if float(Score) < -3.00:
            Tag = "DAMAGING"
    
    Predictions.write(
        "\t".join([ str(idx), dbSNP, protein, substitution, Tag, Score, "|".join([ x['description'] for x in Phenotypes ]), "" ]) + "\n"
    ); return True
            
#
if __name__ == '__main__':
    
    #
    # PARSE PROGRAM ARGUMENTS
    #
    
    parser = OptionParser()
    parser.add_option(
                      "-i",
                      dest    = "input",
                      help    = "process dbSNP rs IDs/protein missense mutations from <INPUT>", 
                      metavar = "<INPUT>",
                      default = None
                      )
    parser.add_option(
                      "-o",
                      dest    = "output",
                      help    = "write predictions/phenotype-associations to <OUTPUT>", 
                      metavar = "<OUTPUT>",
                      default = None
                      )
    parser.add_option(
                      "-w",
                      dest    = "weights",
                      help    = "return weighted predictions using pathogenicity weights <WEIGHTS>", 
                      metavar = "<WEIGHTS>",
                      default = "Inherited"
                      )
    parser.add_option(
                      "-p",
                      dest    = "phenotypes",
                      help    = "append domain-phenotype associations for mutations using phenotype ontology <PHENO>", 
                      metavar = "<PHENO>",
                      default = "DO"
                      )

    (options, args) = parser.parse_args()
    
    #
    # AUTHENTICATE PROGRAM PARAMETERS
    #
    
    if not options.input:
        parser.error("No Input File Given (-i parameter)")
    
    if not options.output:
        parser.error("No Output File Given (-o parameter)")
        
    if not options.weights.upper() in [ "UNWEIGHTED", "INHERITED", "CANCER" ]:
        parser.error("Invalid Weighting Scheme")
    
    #
    # INITIALIZE DATABASE CONNECTION/CURSOR
    #
    
    Config = ConfigParser.ConfigParser()
    Config.read("./config.ini")
        
    dbCursor = \
            MySQLdb.connect(
                host     = str(Config.get("DATABASE", "HOST")),
                port     = int(Config.get("DATABASE", "PORT")),
                user     = str(Config.get("DATABASE", "USER")),
                passwd   = str(Config.get("DATABASE", "PASSWD")),
                db       = str(Config.get("DATABASE", "DB")),
                compress = 1
            ).cursor(MySQLdb.cursors.DictCursor)
    
    #
    # PROCESS MUTATION(S)
    #
    
    Predictions = open("/tmp/" + os.path.basename(os.path.splitext(options.input)[0]) + ".tmp", "w")
    Predictions.write("\t".join([ "#", 
                                  "dbSNP ID",
                                  "Protein ID",
                                  "Substitution",
                                  "Prediction",
                                  "Score",
                                  "Domain-Phenotype Association",
                                  "Warning"
                                ]) + "\n")
    
    idx = 0
    for record in open(options.input, "r"):
        if record and not record.startswith("#"):
            record    = record.strip()
            
            try:
                # dbSNP record ...
                if re.compile("^rs\d+$", re.IGNORECASE).match(record):
                    # ... fetch protein consequence(s)
                    dbCursor.execute("select distinct * from Variants where id='" + record + "'")
                    dbRecords = dbCursor.fetchall()
                    
                    if not dbRecords:
                        # no dbSNP mapping
                        idx += 1
                        
                        Predictions.write(
                            "\t".join([ str(idx), record, "", "", "", "", "", "No dbSNP Mapping(s) For Record" ]) + "\n"
                        ); continue
                    
                    # process dbSNP/protein consequence(s) ...
                    for x in dbRecords:
                        idx += 1
                        
                        process_record(x['id'], x['protein'], x['substitution'])
                else:
                    # parse protein/substitution(s) ...
                    Protein       = record.upper().split()[0]
                    Substitutions = [ x.strip() for x in record.upper().split()[1].split(",") ]
                        
                    for x in Substitutions:
                        idx += 1
                        
                        if x:
                            process_record("-", Protein, x)
            #
            except Exception, e:
                idx += 1
                
                Predictions.write(
                    "\t".join([ str(idx), "", "", "", "", "", "", "An Error Occured While Parsing The Record: " + record ]) + "\n"
                )
            #
        #
    #
    
    Predictions.close()
    
    # move predictions to the requested location
    os.system("mv /tmp/" + os.path.basename(os.path.splitext(options.input)[0]) + ".tmp " + options.output)
