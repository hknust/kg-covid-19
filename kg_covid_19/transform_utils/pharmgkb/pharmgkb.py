#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import os
import tempfile
from collections import defaultdict

from kg_covid_19.transform_utils.transform import Transform
from kg_covid_19.utils.transform_utils import data_to_dict, parse_header, \
    unzip_to_tempdir, write_node_edge_item, get_item_by_priority

"""Ingest PharmGKB drug -> drug target info

Dataset location: https://api.pharmgkb.org/v1/download/file/data/relationships.zip
GitHub Issue: https://github.com/Knowledge-Graph-Hub/kg-covid-19/issues/7

"""




class PharmGKB(Transform):

    def __init__(self, input_dir: str = None, output_dir: str = None):
        source_name = "pharmgkb"
        super().__init__(source_name, input_dir, output_dir)

    def run(self):
        rel_zip_file_name = os.path.join(self.input_base_dir, "relationships.zip")
        relationship_file_name = "relationships.tsv"
        gene_mapping_zip_file = os.path.join(self.input_base_dir, "pharmgkb_genes.zip")
        gene_mapping_file_name = "genes.tsv"
        gene_node_type = "biolink:Protein"
        drug_node_type = "biolink:Drug"
        drug_gene_edge_label = "biolink:interacts_with"
        drug_gene_edge_relation = "RO:0002436"  # molecularly interacts with
        uniprot_curie_prefix = "UniProtKB:"
        self.edge_header = ['subject', 'edge_label', 'object', 'relation']
        self.node_header = ['id', 'name', 'category']
        edge_of_interest = ['Gene', 'Chemical']  # logic also matches 'Chemical'-'Gene'
        #
        # file stuff
        #
        # get relationship file (what we are ingest here)
        relationship_tempdir = tempfile.mkdtemp()
        relationship_file_path = os.path.join(relationship_tempdir,
                                              relationship_file_name)
        unzip_to_tempdir(rel_zip_file_name, relationship_tempdir)
        if not os.path.exists(relationship_file_path):
            raise PharmGKBFileError("Can't find relationship file needed for ingest")

        # get mapping file for gene ids
        gene_id_tempdir = tempfile.mkdtemp()
        gene_mapping_file_path = os.path.join(gene_id_tempdir,
                                              gene_mapping_file_name)
        unzip_to_tempdir(gene_mapping_zip_file, gene_id_tempdir)
        if not os.path.exists(gene_mapping_file_path):
            raise PharmGKBFileError("Can't find gene map file needed for ingest")

        gene_id_map = self.make_gene_id_mapping_file(gene_mapping_file_path)

        #
        # read in and transform relationship.tsv
        #
        with open(relationship_file_path) as relationships, \
                open(self.output_node_file, 'w') as node, \
                open(self.output_edge_file, 'w') as edge:
            # write headers (change default node/edge headers if necessary
            node.write("\t".join(self.node_header) + "\n")
            edge.write("\t".join(self.edge_header) + "\n")

            rel_header = parse_header(relationships.readline())
            for line in relationships:
                line_data = self.parse_pharmgkb_line(line, rel_header)

                if line_data['Entity1_type'] == 'Chemical' and \
                    line_data['Entity2_type'] == 'Gene':
                    logging.warning("Need to parse this!")

                if line_data['Entity1_type'] == 'Gene' and \
                    line_data['Entity2_type'] == 'Chemical':
                    #
                    # make node for Entity 1 (gene)
                    #
                    gene_id = gene_id_map[line_data['Entity1_id']]
                    try:
                        gene_id = \
                            uniprot_curie_prefix + gene_id_map[line_data['Entity1_id']]['parsed_ids']['UniProtKB']
                    except KeyError:
                        logging.warning("Can't find Uniprot ID for gene")

                    write_node_edge_item(fh=node,
                                         header=self.node_header,
                                         data=[gene_id,
                                               line_data['Entity1_name'],
                                               gene_node_type])
                    #
                    # make node for Entity 2 (chemical)
                    #
                    # write_node_edge_item(fh=node,
                    #                      header=self.node_header,
                    #                      data=[drug_id,
                    #                            items_dict['DRUG_NAME'],
                    #                            drug_node_type])

                    #
                    # edge
                    #
                    # ['subject', 'edge_label', 'object', 'relation', 'comment']
                    # write_node_edge_item(fh=edge,
                    #                      header=self.edge_header,
                    #                      data=[drug_id,
                    #                            drug_gene_edge_label,
                    #                            gene_id,
                    #                            drug_gene_edge_relation,
                    #                            items_dict['ACT_COMMENT']])
                    pass

    def parse_pharmgkb_line(self, this_line: str, header_items) -> dict:
        """Parse a single line from relationships.tsv and return a dict with data

        :param this_line: line from relationship.tsv to parse
        :param header_items: header from relationships.tsv
        :return: dict with key value containing data
        """
        items = this_line.strip().split('\t')
        return data_to_dict(header_items, items)

    def make_gene_id_mapping_file(self,
                                  map_file: str,
                                  sep: str = '\t',
                                  pharmgkb_id_col: str = 'PharmGKB Accession Id',
                                  id_key: str = 'Cross-references',
                                  key_parsed_ids: str = 'parsed_ids',
                                  id_sep: str = ',',
                                  id_key_val_sep: str = ':'
                                  ) -> dict:
        """Fxn to parse gene mappings for PharmGKB ids
        What I need is PharmGKB -> uniprot ids, but this parses everything
        They don't make this easy...

        :param map_file: genes.tsv file, containing mappings
        :param pharmgkb_id_col: column containing pharmgkb, to be used as key for map
        :param key_parsed_ids: name of new key to put parsed ids in
        :param sep: separator between columns [\t]
        :param id_key: column name that contains ids [Cross-references]
        :param id_sep: separator between each id key:val pair [,]
        :param id_key_val_sep: separator between key:val pair [:]
        :return:
        """
        map = defaultdict()
        with open(map_file) as f:
            header_items = f.readline().split(sep)
            if pharmgkb_id_col not in header_items:
                raise CantFindPharmGKBKey("Can't find PharmGKB id in map file!")
            for line in f:
                items = line.strip().split(sep)
                dat = data_to_dict(header_items, items)
                if id_key in dat:
                    for item in dat[id_key].split(id_sep):
                        if not item:
                            continue  # not xrefs, skip
                        item = item.strip('\"')  # remove quotes around each item
                        key, value = item.split(id_key_val_sep, 1) # split on first :
                        if key_parsed_ids not in dat:
                            dat[key_parsed_ids] = dict()
                        dat[key_parsed_ids][key] = value
                map[dat[pharmgkb_id_col]] = dat
        return map


class CantFindPharmGKBKey(object):
    pass

class PharmKGBUnsupportedTypeError(object):
    pass

class PharmGKBFileError(Exception):
    pass

