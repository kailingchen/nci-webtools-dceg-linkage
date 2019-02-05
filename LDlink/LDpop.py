#!/usr/bin/env python
import yaml
import json
import math
import os
from pymongo import MongoClient
from bson import json_util, ObjectId
import subprocess
import sys
import time
contents = open("SNP_Query_loginInfo.ini").read().split('\n')
username = contents[0].split('=')[1]
password = contents[1].split('=')[1]
port = int(contents[2].split('=')[1])

# Create LDpop function

def calculate_pop(snp1, snp2, pop, web, request=None):

    # trim any whitespace
    snp1 = snp1.strip()
    snp2 = snp2.strip() 

    # Set data directories using config.yml
    with open('config.yml', 'r') as f:
        config = yaml.load(f)
    dbsnp_version = config['data']['dbsnp_version']
    pop_dir = config['data']['pop_dir']
    vcf_dir = config['data']['vcf_dir']

    tmp_dir = "./tmp/"

    # Ensure tmp directory exists
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)

    # Create JSON output
    output = {}

    # Connect to Mongo snp database
    if web:
        client = MongoClient('mongodb://'+username+':'+password+'@localhost/admin', port)
    else:
        client = MongoClient('localhost', port)
    db = client["LDLink"]

    def get_coords(db, rsid):
        rsid = rsid.strip("rs")
        query_results = db.dbsnp151.find_one({"id": rsid})
        query_results_sanitized = json.loads(json_util.dumps(query_results))
        return query_results_sanitized

    # Query genomic coordinates
    def get_rsnum(db, coord):
        temp_coord = coord.strip("chr").split(":")
        chro = temp_coord[0]
        pos = temp_coord[1]
        query_results = db.dbsnp151.find({"chromosome": chro, "position": pos})
        query_results_sanitized = json.loads(json_util.dumps(query_results))
        return query_results_sanitized

    # Replace input genomic coordinates with variant ids (rsids)
    def replace_coord_rsid(db, snp):
        if snp[0:2] == "rs":
            return snp
        else:
            snp_info_lst = get_rsnum(db, snp)
            print "snp_info_lst"
            print snp_info_lst
            if snp_info_lst != None:
                if len(snp_info_lst) > 1:
                    var_id = "rs" + snp_info_lst[0]['id']
                    ref_variants = []
                    for snp_info in snp_info_lst:
                        if snp_info['id'] == snp_info['ref_id']:
                            ref_variants.append(snp_info['id'])
                    if len(ref_variants) > 1:
                        var_id = "rs" + ref_variants[0]
                        if "warning" in output:
                            output["warning"] = output["warning"] + \
                            ". Multiple rsIDs (" + ", ".join(["rs" + ref_id for ref_id in ref_variants]) + ") map to genomic coordinates " + snp
                        else:
                            output["warning"] = "Multiple rsIDs (" + ", ".join(["rs" + ref_id for ref_id in ref_variants]) + ") map to genomic coordinates " + snp
                    elif len(ref_variants) == 0 and len(snp_info_lst) > 1:
                        var_id = "rs" + snp_info_lst[0]['id']
                        if "warning" in output:
                            output["warning"] = output["warning"] + \
                            ". Multiple rsIDs (" + ", ".join(["rs" + ref_id for ref_id in ref_variants]) + ") map to genomic coordinates " + snp
                        else:
                            output["warning"] = "Multiple rsIDs (" + ", ".join(["rs" + ref_id for ref_id in ref_variants]) + ") map to genomic coordinates " + snp
                    else:
                        var_id = "rs" + ref_variants[0]
                    return var_id
                elif len(snp_info_lst) == 1:
                    var_id = "rs" + snp_info_lst[0]['id']
                    return var_id
                else:
                    return snp
            else:
                return snp
        return snp

    snp1 = replace_coord_rsid(db, snp1)
    snp2 = replace_coord_rsid(db, snp2)

    # Find RS numbers in snp database
    # SNP1
    snp1_coord = get_coords(db, snp1)
    if snp1_coord == None:
        output["error"] = snp1 + " is not in dbSNP build " + dbsnp_version + "."
        return(json.dumps(output, sort_keys=True, indent=2))

    # SNP2
    snp2_coord = get_coords(db, snp2)
    if snp2_coord == None:
        output["error"] = snp2 + " is not in dbSNP build " + dbsnp_version + "."
        return(json.dumps(output, sort_keys=True, indent=2))

    # Check if SNPs are on the same chromosome
    if snp1_coord['chromosome'] != snp2_coord['chromosome']:
        output["warning"] = snp1 + " and " + \
            snp2 + " are on different chromosomes"

    # Select desired ancestral populations
    pops = pop.split("+")
    pop_dirs = []
    for pop_i in pops:
        if pop_i in ["ALL", "AFR", "AMR", "EAS", "EUR", "SAS", "ACB", "ASW", "BEB", "CDX", "CEU", "CHB", "CHS", "CLM", "ESN", "FIN", "GBR", "GIH", "GWD", "IBS", "ITU", "JPT", "KHV", "LWK", "MSL", "MXL", "PEL", "PJL", "PUR", "STU", "TSI", "YRI"]:
            pop_dirs.append(pop_dir + pop_i + ".txt")
        else:
            output["error"] = pop_i + " is not an ancestral population. Choose one of the following ancestral populations: AFR, AMR, EAS, EUR, or SAS; or one of the following sub-populations: ACB, ASW, BEB, CDX, CEU, CHB, CHS, CLM, ESN, FIN, GBR, GIH, GWD, IBS, ITU, JPT, KHV, LWK, MSL, MXL, PEL, PJL, PUR, STU, TSI, or YRI."
            return(json.dumps(output, sort_keys=True, indent=2))

    get_pops = "cat " + " ".join(pop_dirs)
    proc = subprocess.Popen(get_pops, shell=True, stdout=subprocess.PIPE)
    pop_list = proc.stdout.readlines()

    ids = [i.strip() for i in pop_list]
    pop_ids = list(set(ids))

    # Extract 1000 Genomes phased genotypes

    # SNP1
    vcf_file1 = vcf_dir + snp1_coord['chromosome'] + ".phase3_shapeit2_mvncall_integrated_v5.20130502.genotypes.vcf.gz"
    tabix_snp1_offset = "tabix {0} {1}:{2}-{2} | grep -v -e END".format(
        vcf_file1, snp1_coord['chromosome'], snp1_coord['position'])
    proc1_offset = subprocess.Popen(
        tabix_snp1_offset, shell=True, stdout=subprocess.PIPE)
    vcf1_offset = proc1_offset.stdout.readlines()

    # SNP2
    vcf_file2 = vcf_dir + snp2_coord['chromosome'] + ".phase3_shapeit2_mvncall_integrated_v5.20130502.genotypes.vcf.gz"
    tabix_snp2_offset = "tabix {0} {1}:{2}-{2} | grep -v -e END".format(
        vcf_file2, snp2_coord['chromosome'], snp2_coord['position'])
    proc2_offset = subprocess.Popen(
        tabix_snp2_offset, shell=True, stdout=subprocess.PIPE)
    vcf2_offset = proc2_offset.stdout.readlines()

    vcf1_pos = snp1_coord['position']
    vcf2_pos = snp2_coord['position']
    vcf1 = vcf1_offset
    vcf2 = vcf2_offset

    # Import SNP VCF files

    # SNP1
    if len(vcf1) == 0:
        output["error"] = snp1 + " is not in 1000G reference panel."
        return(json.dumps(output, sort_keys=True, indent=2))
    elif len(vcf1) > 1:
        geno1 = []
        for i in range(len(vcf1)):
            if vcf1[i].strip().split()[2] == snp1:
                geno1 = vcf1[i].strip().split()
        if geno1 == []:
            output["error"] = snp1 + " is not in 1000G reference panel."
            return(json.dumps(output, sort_keys=True, indent=2))
    else:
        geno1 = vcf1[0].strip().split()

    if geno1[2] != snp1:
        if "warning" in output:
            output["warning"] = output["warning"] + \
                ". Genomic position for query variant1 (" + snp1 + \
                ") does not match RS number at 1000G position (chr" + \
                geno1[0]+":"+geno1[1]+")"
        else:
            output["warning"] = "Genomic position for query variant1 (" + snp1 + \
                ") does not match RS number at 1000G position (chr" + \
                geno1[0]+":"+geno1[1]+")"
        snp1 = geno1[2]

    if "," in geno1[3] or "," in geno1[4]:
        output["error"] = snp1 + " is not a biallelic variant."
        return(json.dumps(output, sort_keys=True, indent=2))

    if len(geno1[3]) == 1 and len(geno1[4]) == 1:
        snp1_a1 = geno1[3]
        snp1_a2 = geno1[4]
    elif len(geno1[3]) == 1 and len(geno1[4]) > 1:
        snp1_a1 = "-"
        snp1_a2 = geno1[4][1:]
    elif len(geno1[3]) > 1 and len(geno1[4]) == 1:
        snp1_a1 = geno1[3][1:]
        snp1_a2 = "-"
    elif len(geno1[3]) > 1 and len(geno1[4]) > 1:
        snp1_a1 = geno1[3][1:]
        snp1_a2 = geno1[4][1:]

    allele1 = {"0|0": [snp1_a1, snp1_a1], "0|1": [snp1_a1, snp1_a2], "1|0": [snp1_a2, snp1_a1], "1|1": [
        snp1_a2, snp1_a2], "0": [snp1_a1, "."], "1": [snp1_a2, "."], "./.": [".", "."], ".": [".", "."]}

    # SNP2
    if len(vcf2) == 0:
        output["error"] = snp2 + " is not in 1000G reference panel."
        return(json.dumps(output, sort_keys=True, indent=2))
    elif len(vcf2) > 1:
        geno2 = []
        for i in range(len(vcf2)):
            if vcf2[i].strip().split()[2] == snp2:
                geno2 = vcf2[i].strip().split()
        if geno2 == []:
            output["error"] = snp2 + " is not in 1000G reference panel."
            return(json.dumps(output, sort_keys=True, indent=2))
    else:
        geno2 = vcf2[0].strip().split()

    if geno2[2] != snp2:
        if "warning" in output:
            output["warning"] = output["warning"] + \
                ". Genomic position for query variant2 (" + snp2 + \
                ") does not match RS number at 1000G position (chr" + \
                geno2[0]+":"+geno2[1]+")"
        else:
            output["warning"] = "Genomic position for query variant2 (" + snp2 + \
                ") does not match RS number at 1000G position (chr" + \
                geno2[0]+":"+geno2[1]+")"
        snp2 = geno2[2]

    if "," in geno2[3] or "," in geno2[4]:
        output["error"] = snp2 + " is not a biallelic variant."
        return(json.dumps(output, sort_keys=True, indent=2))

    if len(geno2[3]) == 1 and len(geno2[4]) == 1:
        snp2_a1 = geno2[3]
        snp2_a2 = geno2[4]
    elif len(geno2[3]) == 1 and len(geno2[4]) > 1:
        snp2_a1 = "-"
        snp2_a2 = geno2[4][1:]
    elif len(geno2[3]) > 1 and len(geno2[4]) == 1:
        snp2_a1 = geno2[3][1:]
        snp2_a2 = "-"
    elif len(geno2[3]) > 1 and len(geno2[4]) > 1:
        snp2_a1 = geno2[3][1:]
        snp2_a2 = geno2[4][1:]

    allele2 = {"0|0": [snp2_a1, snp2_a1], "0|1": [snp2_a1, snp2_a2], "1|0": [snp2_a2, snp2_a1], "1|1": [
        snp2_a2, snp2_a2], "0": [snp2_a1, "."], "1": [snp2_a2, "."], "./.": [".", "."], ".": [".", "."]}

    if geno1[1] != vcf1_pos:
        output["error"] = "VCF File does not match variant coordinates for SNP1."
        return(json.dumps(output, sort_keys=True, indent=2))

    if geno2[1] != vcf2_pos:
        output["error"] = "VCF File does not match variant coordinates for SNP2."
        return(json.dumps(output, sort_keys=True, indent=2))

    # Get headers
    tabix_snp1_h = "tabix -H {0} | grep CHROM".format(vcf_file1)
    proc1_h = subprocess.Popen(
        tabix_snp1_h, shell=True, stdout=subprocess.PIPE)
    head1 = proc1_h.stdout.readlines()[0].strip().split()

    tabix_snp2_h = "tabix -H {0} | grep CHROM".format(vcf_file2)
    proc2_h = subprocess.Popen(
        tabix_snp2_h, shell=True, stdout=subprocess.PIPE)
    head2 = proc2_h.stdout.readlines()[0].strip().split()

    # Combine phased genotypes
    geno = {}
    for i in range(9, len(head1)):
        geno[head1[i]] = [allele1[geno1[i]], ".."]

    for i in range(9, len(head2)):
        if head2[i] in geno:
            geno[head2[i]][1] = allele2[geno2[i]]

    # Extract haplotypes
    hap = {}
    for ind in pop_ids:
        if ind in geno:
            hap1 = geno[ind][0][0] + "_" + geno[ind][1][0]
            hap2 = geno[ind][0][1] + "_" + geno[ind][1][1]

            if hap1 in hap:
                hap[hap1] += 1
            else:
                hap[hap1] = 1

            if hap2 in hap:
                hap[hap2] += 1
            else:
                hap[hap2] = 1

    # Remove missing haplotypes
    keys = hap.keys()
    for key in keys:
        if "." in key:
            hap.pop(key, None)

    # Check all haplotypes are present
    if len(hap) != 4:
        snp1_a = [snp1_a1, snp1_a2]
        snp2_a = [snp2_a1, snp2_a2]
        haps = [snp1_a[0] + "_" + snp2_a[0], snp1_a[0] + "_" + snp2_a[1],
                snp1_a[1] + "_" + snp2_a[0], snp1_a[1] + "_" + snp2_a[1]]
        for i in haps:
            if i not in hap:
                hap[i] = 0

    # Sort haplotypes
    A = hap[sorted(hap)[0]]
    B = hap[sorted(hap)[1]]
    C = hap[sorted(hap)[2]]
    D = hap[sorted(hap)[3]]
    N = A + B + C + D
    tmax = max(A, B, C, D)

    hap1 = sorted(hap, key=hap.get, reverse=True)[0]
    hap2 = sorted(hap, key=hap.get, reverse=True)[1]
    hap3 = sorted(hap, key=hap.get, reverse=True)[2]
    hap4 = sorted(hap, key=hap.get, reverse=True)[3]

    delta = float(A * D - B * C)
    Ms = float((A + C) * (B + D) * (A + B) * (C + D))
    if Ms != 0:

        # D prime
        if delta < 0:
            D_prime = abs(delta / min((A + C) * (A + B), (B + D) * (C + D)))
        else:
            D_prime = abs(delta / min((A + C) * (C + D), (A + B) * (B + D)))

        # R2
        r2 = (delta**2) / Ms

        # P-value
        num = (A + B + C + D) * (A * D - B * C)**2
        denom = Ms
        chisq = num / denom
        p = 2 * (1 - (0.5 * (1 + math.erf(chisq**0.5 / 2**0.5))))

    else:
        D_prime = "NA"
        r2 = "NA"
        chisq = "NA"
        p = "NA"

    # Find Correlated Alleles
    if r2 > 0.1 and r2 != "NA":

        # Expected Cell Counts
        eA = (A + B) * (A + C) / N
        eB = (B + A) * (B + D) / N
        eC = (C + A) * (C + D) / N
        eD = (D + C) * (D + B) / N

        # Calculate Deltas
        dA = (A - eA)**2
        dB = (B - eB)**2
        dC = (C - eC)**2
        dD = (D - eD)**2
        dmax = max(dA, dB, dC, dD)

        if dA == dB == dC == dD:
            if tmax == A or tmax == D:
                corr1 = snp1 + "(" + sorted(hap)[0].split("_")[
                    0] + ") allele is correlated with " + snp2 + "(" + sorted(hap)[0].split("_")[1] + ") allele"
                corr2 = snp1 + "(" + sorted(hap)[2].split("_")[
                    0] + ") allele is correlated with " + snp2 + "(" + sorted(hap)[1].split("_")[1] + ") allele"
                corr_alleles = [corr1, corr2]
            else:
                corr1 = snp1 + "(" + sorted(hap)[0].split("_")[
                    0] + ") allele is correlated with " + snp2 + "(" + sorted(hap)[1].split("_")[1] + ") allele"
                corr2 = snp1 + "(" + sorted(hap)[2].split("_")[
                    0] + ") allele is correlated with " + snp2 + "(" + sorted(hap)[0].split("_")[1] + ") allele"
                corr_alleles = [corr1, corr2]
        elif dmax == dA or dmax == dD:
            corr1 = snp1 + "(" + sorted(hap)[0].split("_")[0] + ") allele is correlated with " + \
                snp2 + "(" + sorted(hap)[0].split("_")[1] + ") allele"
            corr2 = snp1 + "(" + sorted(hap)[2].split("_")[0] + ") allele is correlated with " + \
                snp2 + "(" + sorted(hap)[1].split("_")[1] + ") allele"
            corr_alleles = [corr1, corr2]
        else:
            corr1 = snp1 + "(" + sorted(hap)[0].split("_")[0] + ") allele is correlated with " + \
                snp2 + "(" + sorted(hap)[1].split("_")[1] + ") allele"
            corr2 = snp1 + "(" + sorted(hap)[2].split("_")[0] + ") allele is correlated with " + \
                snp2 + "(" + sorted(hap)[0].split("_")[1] + ") allele"
            corr_alleles = [corr1, corr2]
    else:
        corr_alleles = [snp1 + " and " + snp2 + " are in linkage equilibrium"]

    # Create JSON output
    snp_1 = {}
    snp_1["rsnum"] = snp1
    snp_1["coord"] = "chr" + snp1_coord['chromosome'] + ":" + \
        vcf1_pos

    snp_1_allele_1 = {}
    snp_1_allele_1["allele"] = sorted(hap)[0].split("_")[0]
    snp_1_allele_1["count"] = str(A + B)
    snp_1_allele_1["frequency"] = str(round(float(A + B) / N, 3))
    snp_1["allele_1"] = snp_1_allele_1

    snp_1_allele_2 = {}
    snp_1_allele_2["allele"] = sorted(hap)[2].split("_")[0]
    snp_1_allele_2["count"] = str(C + D)
    snp_1_allele_2["frequency"] = str(round(float(C + D) / N, 3))
    snp_1["allele_2"] = snp_1_allele_2
    output["snp1"] = snp_1

    snp_2 = {}
    snp_2["rsnum"] = snp2
    snp_2["coord"] = "chr" + snp2_coord['chromosome'] + ":" + \
        vcf2_pos

    snp_2_allele_1 = {}
    snp_2_allele_1["allele"] = sorted(hap)[0].split("_")[1]
    snp_2_allele_1["count"] = str(A + C)
    snp_2_allele_1["frequency"] = str(round(float(A + C) / N, 3))
    snp_2["allele_1"] = snp_2_allele_1

    snp_2_allele_2 = {}
    snp_2_allele_2["allele"] = sorted(hap)[1].split("_")[1]
    snp_2_allele_2["count"] = str(B + D)
    snp_2_allele_2["frequency"] = str(round(float(B + D) / N, 3))
    snp_2["allele_2"] = snp_2_allele_2
    output["snp2"] = snp_2

    two_by_two = {}
    cells = {}
    cells["c11"] = str(A)
    cells["c12"] = str(B)
    cells["c21"] = str(C)
    cells["c22"] = str(D)
    two_by_two["cells"] = cells
    two_by_two["total"] = str(N)
    output["two_by_two"] = two_by_two

    haplotypes = {}
    hap_1 = {}
    hap_1["alleles"] = hap1
    hap_1["count"] = str(hap[hap1])
    hap_1["frequency"] = str(round(float(hap[hap1]) / N, 3))
    haplotypes["hap1"] = hap_1

    hap_2 = {}
    hap_2["alleles"] = hap2
    hap_2["count"] = str(hap[hap2])
    hap_2["frequency"] = str(round(float(hap[hap2]) / N, 3))
    haplotypes["hap2"] = hap_2

    hap_3 = {}
    hap_3["alleles"] = hap3
    hap_3["count"] = str(hap[hap3])
    hap_3["frequency"] = str(round(float(hap[hap3]) / N, 3))
    haplotypes["hap3"] = hap_3

    hap_4 = {}
    hap_4["alleles"] = hap4
    hap_4["count"] = str(hap[hap4])
    hap_4["frequency"] = str(round(float(hap[hap4]) / N, 3))
    haplotypes["hap4"] = hap_4
    output["haplotypes"] = haplotypes

    statistics = {}
    if Ms != 0:
        statistics["d_prime"] = str(round(D_prime, 4))
        statistics["r2"] = str(round(r2, 4))
        statistics["chisq"] = str(round(chisq, 4))
        if p >= 0.0001:
            statistics["p"] = str(round(p, 4))
        else:
            statistics["p"] = "<0.0001"
    else:
        statistics["d_prime"] = D_prime
        statistics["r2"] = r2
        statistics["chisq"] = chisq
        statistics["p"] = p

    output["statistics"] = statistics

    output["corr_alleles"] = corr_alleles

    # Generate output file
    # ldpair_out = open(tmp_dir + "LDpair_" + request + ".txt", "w")
    # print >> ldpair_out, "Query SNPs:"
    # print >> ldpair_out, output["snp1"]["rsnum"] + \
    #     " (" + output["snp1"]["coord"] + ")"
    # print >> ldpair_out, output["snp2"]["rsnum"] + \
    #     " (" + output["snp2"]["coord"] + ")"
    # print >> ldpair_out, ""
    # print >> ldpair_out, pop + " Haplotypes:"
    # print >> ldpair_out, " " * 15 + output["snp2"]["rsnum"]
    # print >> ldpair_out, " " * 15 + \
    #     output["snp2"]["allele_1"]["allele"] + " " * \
    #     7 + output["snp2"]["allele_2"]["allele"]
    # print >> ldpair_out, " " * 13 + "-" * 17
    # print >> ldpair_out, " " * 11 + output["snp1"]["allele_1"]["allele"] + " | " + output["two_by_two"]["cells"]["c11"] + " " * (5 - len(output["two_by_two"]["cells"]["c11"])) + " | " + output["two_by_two"]["cells"]["c12"] + " " * (
    #     5 - len(output["two_by_two"]["cells"]["c12"])) + " | " + output["snp1"]["allele_1"]["count"] + " " * (5 - len(output["snp1"]["allele_1"]["count"])) + " (" + output["snp1"]["allele_1"]["frequency"] + ")"
    # print >> ldpair_out, output["snp1"]["rsnum"] + " " * \
    #     (10 - len(output["snp1"]["rsnum"])) + " " * 3 + "-" * 17
    # print >> ldpair_out, " " * 11 + output["snp1"]["allele_2"]["allele"] + " | " + output["two_by_two"]["cells"]["c21"] + " " * (5 - len(output["two_by_two"]["cells"]["c21"])) + " | " + output["two_by_two"]["cells"]["c22"] + " " * (
    #     5 - len(output["two_by_two"]["cells"]["c22"])) + " | " + output["snp1"]["allele_2"]["count"] + " " * (5 - len(output["snp1"]["allele_2"]["count"])) + " (" + output["snp1"]["allele_2"]["frequency"] + ")"
    # print >> ldpair_out, " " * 13 + "-" * 17
    # print >> ldpair_out, " " * 15 + output["snp2"]["allele_1"]["count"] + " " * (5 - len(output["snp2"]["allele_1"]["count"])) + " " * 3 + output["snp2"]["allele_2"]["count"] + " " * (
    #     5 - len(output["snp2"]["allele_2"]["count"])) + " " * 3 + output["two_by_two"]["total"]
    # print >> ldpair_out, " " * 14 + "(" + output["snp2"]["allele_1"]["frequency"] + ")" + " " * (5 - len(output["snp2"]["allele_1"]["frequency"])) + \
    #     " (" + output["snp2"]["allele_2"]["frequency"] + ")" + \
    #     " " * (5 - len(output["snp2"]["allele_2"]["frequency"]))
    # print >> ldpair_out, ""
    # print >> ldpair_out, "          " + output["haplotypes"]["hap1"]["alleles"] + ": " + \
    #     output["haplotypes"]["hap1"]["count"] + \
    #     " (" + output["haplotypes"]["hap1"]["frequency"] + ")"
    # print >> ldpair_out, "          " + output["haplotypes"]["hap2"]["alleles"] + ": " + \
    #     output["haplotypes"]["hap2"]["count"] + \
    #     " (" + output["haplotypes"]["hap2"]["frequency"] + ")"
    # print >> ldpair_out, "          " + output["haplotypes"]["hap3"]["alleles"] + ": " + \
    #     output["haplotypes"]["hap3"]["count"] + \
    #     " (" + output["haplotypes"]["hap3"]["frequency"] + ")"
    # print >> ldpair_out, "          " + output["haplotypes"]["hap4"]["alleles"] + ": " + \
    #     output["haplotypes"]["hap4"]["count"] + \
    #     " (" + output["haplotypes"]["hap4"]["frequency"] + ")"
    # print >> ldpair_out, ""
    # print >> ldpair_out, "          D': " + output["statistics"]["d_prime"]
    # print >> ldpair_out, "          R2: " + output["statistics"]["r2"]
    # print >> ldpair_out, "      Chi-sq: " + output["statistics"]["chisq"]
    # print >> ldpair_out, "     p-value: " + output["statistics"]["p"]
    # print >> ldpair_out, ""
    # if len(output["corr_alleles"]) == 2:
    #     print >> ldpair_out, output["corr_alleles"][0]
    #     print >> ldpair_out, output["corr_alleles"][1]
    # else:
    #     print >> ldpair_out, output["corr_alleles"][0]

    # try:
    #     output["warning"]
    # except KeyError:
    #     www = "do nothing"
    # else:
    #     print >> ldpair_out, "WARNING: " + output["warning"] + "!"
    # ldpair_out.close()

    # Return output
    return(json.dumps(output, sort_keys=True, indent=2))


def main():
    import json
    import sys

    # Import LDpair options
    if len(sys.argv) == 6:
        snp1 = sys.argv[1]
        snp2 = sys.argv[2]
        pop = sys.argv[3]
        web = sys.argv[4]
        request = sys.argv[5]
    elif sys.argv[4] is False:
        snp1 = sys.argv[1]
        snp2 = sys.argv[2]
        pop = sys.argv[3]
        web = sys.argv[4]
        request = str(time.strftime("%I%M%S"))
    else:
        print "Correct useage is: LDpop.py snp1 snp2 populations request false"
        sys.exit()

    # Run function
    out_json = calculate_pop(snp1, snp2, pop, web, request)

    # Print output
    json_dict = json.loads(out_json)
    # print json_dict

if __name__ == "__main__":
    main()
