# -*- coding: utf-8 -*-
# Copyright 2016-2018 Fabian Hofmann (FIAS), Jonas Hoersch (KIT, IAI) and
# Fabian Gotzens (FZJ, IEK-STE)

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Functions for vertically cleaning a dataset.
"""
from __future__ import absolute_import, print_function

from .config import get_config
from .duke import duke
from .utils import _data_out

import numpy as np
import pandas as pd
import networkx as nx
import logging
logger = logging.getLogger(__name__)


def clean_powerplantname(df):
    """
    Cleans the column "Name" of the database by deleting very frequent
    words, numericals and nonalphanumerical characters of the
    column. Returns a reduced dataframe with nonempty Name-column.

    Parameters
    ----------
    df : pandas.Dataframe
        dataframe to be cleaned

    """
    df = df[df.Name.notnull()]
    name = df.Name.replace(regex=True, value=' ',
                           to_replace=['-', '/', ',', '\(', '\)', '\[', '\]',
                                       '"', '_', '\+', '[0-9]'])

    common_words = pd.Series(sum(name.str.split(), [])).value_counts()
    cw = list(common_words[common_words >= 20].index)

    pattern = [('(?i)(^|\s)'+x+'(?=\s|$)')
               for x in (cw +
                         ['[a-z]', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII',
                          'VIII', 'IX', 'X', 'XI', 'Grupo', 'parque', 'eolico',
                          'gas', 'biomasa', 'COGENERACION', 'gt', 'unnamed',
                          'tratamiento de purines', 'planta', 'de', 'la',
                          'station', 'power', 'storage', 'plant', 'stage',
                          'pumped', 'project', 'dt', 'gud', 'hkw', 'kbr',
                          'Kernkraft', 'Kernkraftwerk', 'kwg', 'krb', 'ohu',
                          'gkn', 'Gemeinschaftskernkraftwerk', 'kki', 'kkp',
                          'kle', 'wkw', 'rwe', 'bis', 'nordsee', 'ostsee',
                          'dampfturbinenanlage', 'ikw', 'kw', 'kohlekraftwerk',
                          'raffineriekraftwerk', 'Kraftwerke'])]
    name = (name
            .replace(regex=True, to_replace=pattern, value=' ')
            .replace('\s+', ' ', regex=True)
            .replace('"', '', regex=True)
            .str.strip()
            .str.capitalize())

    return (df
            .assign(Name=name)
            .loc[lambda x: x.Name != '']
            .sort_values('Name')
            .reset_index(drop=True))


def gather_fueltype_info(df, search_col=['Name', 'Technology']):
    """
    Parses in search_col columns for distinct coal specifications, e.g.
    'lignite', and passes this information to the 'Fueltype' column.

    Parameter
    ---------
    search_col : list, default is ['Name', 'Technology']
        Specify the columns to be parsed
    """
    fueltype = pd.Series(df['Fueltype'])

    for i in search_col:
        found_b = df[i].dropna().str.contains('(?i)lignite|brown')
        fueltype.loc[found_b.reindex(fueltype.index,
                                     fill_value=False)] = 'Lignite'
    fueltype.replace({'Coal': 'Hard Coal'}, inplace=True)

    return df.assign(Fueltype=fueltype)


def gather_technology_info(df, search_col=['Name', 'Fueltype'],
                           config=None):
    """
    Parses in search_col columns for distinct technology specifications, e.g.
    'Run-of-River', and passes this information to the 'Technology' column.

    Parameter
    ---------
    search_col : list, default is ['Name', 'Fueltype']
        Specify the columns to be parsed
    config : dict, default None
        Add custom specific configuration,
        e.g. powerplantmatching.config.get_config(target_countries='Italy'),
        defaults to powerplantmatching.config.get_config()

    """
    if config is None:
        config = get_config()

    technology = (df['Technology'].dropna()
                  if 'Technology' in df
                  else pd.Series())

    pattern = '|'.join(('(?i)'+x) for x in config['target_technologies'])
    for i in search_col:
        found = (df[i].dropna()
                 .str.findall(pattern)
                 .loc[lambda s: s.str.len() > 0]
                 .str.join(sep=', '))

        exists_i = technology.index.intersection(found.index)
        if len(exists_i) > 0:
            technology.loc[exists_i] = (technology.loc[exists_i].str
                                        .cat(found.loc[exists_i], sep=', '))

        new_i = found.index.difference(technology.index)
        technology = technology.append(found[new_i])

    return df.assign(Technology=technology)


def gather_set_info(df, search_col=['Name', 'Fueltype', 'Technology']):
    """
    Parses in search_col columns for distinct set specifications, e.g.
    'Store', and passes this information to the 'Set' column.

    Parameter
    ---------
    search_col : list, default is ['Name', 'Fueltype', 'Technology']
        Specify the columns to be parsed
    config : dict, default None
        Add custom specific configuration,
        e.g. powerplantmatching.config.get_config(target_countries='Italy'),
        defaults to powerplantmatching.config.get_config()

    """
    Set = (df['Set'].copy()
           if 'Set' in df
           else pd.Series(index=df.index))

    pattern = '|'.join(['heizkraftwerk', 'hkw', 'chp', 'bhkw', 'cogeneration',
                        'power and heat', 'heat and power'])
    for i in search_col:
        isCHP_b = df[i].dropna().str.contains(pattern, case=False)\
                    .reindex(df.index).fillna(False)
        Set.loc[isCHP_b] = 'CHP'

    pattern = '|'.join(['battery', 'storage'])
    for i in search_col:
        isStore_b = df[i].dropna().str.contains(pattern, case=False) \
                    .reindex(df.index).fillna(False)
        Set.loc[isStore_b] = 'Store'

    df = df.assign(Set=Set)
    df.loc[:, 'Set'].fillna('PP', inplace=True)
    return df


def clean_technology(df, generalize_hydros=False):
    """
    Clean the 'Technology' by condensing down the value into one claim. This
    procedure might reduce the scope of information, however is crucial for
    comparing different data sources.

    Parameter
    ---------
    search_col : list, default is ['Name', 'Fueltype', 'Technology']
        Specify the columns to be parsed
    config : dict, default None
        Add custom specific configuration,
        e.g. powerplantmatching.config.get_config(target_countries='Italy'),
        defaults to powerplantmatching.config.get_config()

    """
    tech = df['Technology'].dropna()
    if len(tech) == 0:
        return df
    tech = tech.replace(
            {' and ': ', ', ' Power Plant': '', 'Battery': ''}, regex=True)
    if generalize_hydros:
        tech[tech.str.contains('pump', case=False)] = 'Pumped Storage'
        tech[tech.str.contains('reservoir|lake', case=False)] = 'Reservoir'
        tech[tech.str.contains('run-of-river|weir|water', case=False)] =\
            'Run-Of-River'
        tech[tech.str.contains('dam', case=False)] = 'Reservoir'
    tech = tech.replace({'Gas turbine': 'OCGT'})
    tech[tech.str.contains('combined cycle|combustion', case=False)] = 'CCGT'
    tech[tech.str.contains('steam turbine|critical thermal', case=False)] =\
        'Steam Turbine'
    tech[tech.str.contains('ocgt|open cycle', case=False)] = 'OCGT'
    tech = (tech.str.title()
                .str.split(', ')
                .apply(lambda x: ', '.join(i.strip() for i in np.unique(x))))
    tech = tech.replace({'Ccgt': 'CCGT', 'Ocgt': 'OCGT'}, regex=True)
    return df.assign(Technology=tech)


def cliques(df, dataduplicates):
    """
    Locate cliques of units which are determined to belong to the same
    powerplant.  Return the same dataframe with an additional column
    "grouped" which indicates the group that the powerplant is
    belonging to.

    Parameters
    ----------
    df : pandas.Dataframe or string
        dataframe or csv-file which should be analysed
    dataduplicates : pandas.Dataframe or string
        dataframe or name of the csv-linkfile which determines the
        link within one dataset
    """
#    df = read_csv_if_string(df)
    G = nx.DiGraph()
    G.add_nodes_from(df.index)
    G.add_edges_from((r.one, r.two) for r in dataduplicates.itertuples())
    H = G.to_undirected(reciprocal=True)

    grouped = pd.Series(np.nan, index=df.index)
    for i, inds in enumerate(nx.algorithms.clique.find_cliques(H)):
        grouped.loc[inds] = i

    return df.assign(grouped=grouped)


def aggregate_units(df, dataset_name=None,
                    pre_clean_name=True,
                    save_aggregation=True,
                    use_saved_aggregation=False,
                    config=None):
    """
    Vertical cleaning of the database. Cleans the "Name"-column, sums
    up the capacity of powerplant units which are determined to belong
    to the same plant.

    Parameters
    ----------
    df : pandas.Dataframe or string
        Dataframe or name to use for the resulting database
    dataset_name : str, default None
        Specify the name of your df, required if use_saved_aggregation is set
        to True.
    pre_clean_name : Boolean, default True
        Whether to clean the 'Name'-column before aggregating.
    use_saved_aggregation : bool (default False):
        Whether to use the automaticly saved aggregation file, which
        is stored in data/out/default/aggregations/aggregation_groups_XX.csv
        with XX being the name for the dataset. This saves time if you
        want to have aggregated powerplants without running the
        aggregation algorithm again
    """
    if config is None:
        config = get_config()

    def most_frequent(ds):
        return ds.value_counts(dropna=False).index[0]

    weighted_cols = [col for col in ['Efficiency', 'Duration']
                     if col in config['target_columns']]
    df = (df.assign(**{col: df[col] * df.Capacity for col in weighted_cols})
            .assign(lat=df.lat.astype(float),
                    lon=df.lon.astype(float)))

    props_for_groups = pd.Series({
                'Name': most_frequent,
                'Country': most_frequent,
                'Fueltype': most_frequent,
                'Technology': most_frequent,
                'Set': most_frequent,
                'File': most_frequent,
                'Capacity': pd.Series.sum,
                'lat': pd.Series.mean,
                'lon': pd.Series.mean,
                'YearCommissioned': pd.Series.min,
                'Retrofit': pd.Series.max,
                'projectID': pd.Series.tolist,
                'Duration': pd.Series.sum,  # note this is weighted sum
                'Efficiency': pd.Series.mean  # note this is weighted mean
                })[config['target_columns']].to_dict()

    if pre_clean_name:
        logger.info("Cleaning plant names in '{}'.".format(dataset_name))
        df = clean_powerplantname(df)

    logger.info("Aggregating blocks to entire units in '{}'."
                .format(dataset_name))

    path_name = _data_out('aggregations/aggregation_groups_{}.csv'
                          .format(dataset_name), config=config)

    if use_saved_aggregation & save_aggregation:
        try:
            logger.info("Reading saved aggregation groups for dataset '{}'."
                        .format(dataset_name))
            groups = (pd.read_csv(path_name, header=None, index_col=0)
                        .reindex(index=df.index))
            df = df.assign(grouped=groups.values)
        except (ValueError, IOError):
            logger.warning("Non-existing saved aggregation groups for dataset"
                           " '{0}', continuing by aggregating again"
                           .format(dataset_name))
            if 'grouped' in df:
                df.drop('grouped', axis=1, inplace=True)

    if 'grouped' not in df:
        duplicates = duke(df)
        df = cliques(df, duplicates)
        if save_aggregation:
            df.grouped.to_csv(path_name)
    df = df.groupby('grouped').agg(props_for_groups)
    df = (df
          .assign(**{col: df[col].div(df['Capacity'])
                  for col in weighted_cols})
          .reset_index(drop=True)
          .pipe(clean_powerplantname)
          .reindex(columns=config['target_columns']))
    return df


# def clean_single(df, dataset_name=None,
#                 aggregate_powerplant_units=True,
#                 use_saved_aggregation=False,
#                 return_aggregation_groups=False,
#                 config=None):
#    """
#    Vertical cleaning of the database. Cleans the "Name"-column, sums
#    up the capacity of powerplant units which are determined to belong
#    to the same plant.
#
#    Parameters
#    ----------
#    df : pandas.Dataframe or string
#        dataframe or csv-file to use for the resulting database
#
#    dataset_name : str
#        Only sensible if ``aggregate_units`` is set to True.  custom name
#        for dataset identification, choose your own identification in
#        case no metadata is passed to the function
#
#    aggregate_units : Boolean, default True
#        Whether or not the power plant units should be aggregated
#
#    use_saved_aggregation : Boolean, default False
#        Only sensible if aggregate_units is set to True.
#        Whether to use the automatically saved aggregation file, which
#        is stored in data/aggregation_groups_XX.csv with XX
#        being either a custom name for the dataset or the name passed
#        with the metadata of the pd.DataFrame. This saves time if you
#        want to have aggregated powerplants without running the
#        aggregation algorithm again
#
#    """
#    if config is None:
#        config = get_config()
#
#    if (aggregate_powerplant_units and use_saved_aggregation and
#       dataset_name is None):
#            raise ValueError('``aggregate_powerplant_units`` is True but no '
#                             '``dataset_name`` was given!')
#    if dataset_name is None:
#        dataset_name = 'Unnamed dataset'
#
#    logger.info("Cleaning plant names in '{}'.".format(dataset_name))
#    df = clean_powerplantname(df)
#
#    if aggregate_powerplant_units:
#        if return_aggregation_groups:
#            df, grouped = aggregate_units(
#                    df, use_saved_aggregation=use_saved_aggregation,
#                    dataset_name=dataset_name,
#                    return_aggregation_groups=True,
#                    config=config)
#        else:
#            df = aggregate_units(df,
#                                 use_saved_aggregation=use_saved_aggregation,
#                                 dataset_name=dataset_name,
#                                 config=config)
#
#    else:
#        df['projectID'] = df['projectID'].dropna().map(lambda x: [x])
#    if return_aggregation_groups:
#        return df, grouped
#    else:
#        return df
