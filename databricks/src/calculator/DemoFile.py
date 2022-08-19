# Databricks notebook source
# Importing Libraries
from pyspark.sql.functions import *
from itertools import chain
from pyspark.sql.types import DateType, DoubleType, IntegerType,StringType
from IPython.core.interactiveshell import InteractiveShell
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# COMMAND ----------

# Creating tables
spark.sql("set spark.sql.legacy.timeParserPolicy=LEGACY")
spark.conf.set("spark.sql.legacy.allowCreatingManagedTableUsingNonemptyLocation","true")
InteractiveShell.ast_node_interactivity = "all"

# COMMAND ----------

# Reading the db environment
db_environment = dbutils.widgets.get('db_environment')
#db_environment='gac_afr'

# COMMAND ----------

# Refreshing the tables for input
spark.sql(f"refresh table {db_environment}.gh_ihs_data_raw")
spark.sql(f"refresh table {db_environment}.gh_master_data_raw")
spark.sql(f"refresh table {db_environment}.gh_sku_mapping_raw")
spark.sql(f"refresh table {db_environment}.key_design_config")
spark.sql(f"refresh table {db_environment}.country_code_mapping")

# COMMAND ----------

# Reading input tables
gh_feature_data_df = spark.read.table(f"{db_environment}.gh_ihs_data_raw")
gh_master_data_df = spark.read.table(f"{db_environment}.gh_master_data_raw")
gh_sku_mapping_df = spark.read.table(f"{db_environment}.gh_sku_mapping_raw")

# COMMAND ----------

# fetching country codes and key structure
country_name = "Ghana"
country_code = spark.sql(f'select country_code from {db_environment}.country_code_mapping where country_name = "'+ country_name + '"').collect()[0][0]
key_columns = spark.sql(f'select key_columns from {db_environment}.key_design_config where country_code ="'+country_code+ '" and active_flag= 1').collect()[0][0]
key_columns_list = key_columns.split(',')

# COMMAND ----------

#display(gh_feature_data_df)

# COMMAND ----------

# Getting regressor data in proper data type
gh_feature_data_df = gh_feature_data_df.withColumn('Date', to_date(col("Date"), "yyyy-MM-dd"))

cols_int = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'q1', 'q2', 'q3', 'q4']
cols_double = ['max_T_last4Yrs', 'precipitation', 'REAL_GDP_lcu_month_Oct', 'REAL_Gross_Domestic_Demand_lcu_month_Oct', 'REAL_Fixed_Investment_lcu_month_Oct', 'Participation_Rate_annual_Aug']

for c in gh_feature_data_df.columns:
  if c in cols_int:
    gh_feature_data_df = gh_feature_data_df.withColumn(c, gh_feature_data_df[c].cast(IntegerType()))
  elif c in cols_double:
    gh_feature_data_df = gh_feature_data_df.withColumn(c, gh_feature_data_df[c].cast(DoubleType()))
#display(gh_feature_data_df)

# COMMAND ----------

# check if key_columns present in master data table
for i in key_columns_list:
  if(i not in gh_master_data_df.columns ):
#     pass
#   else:
    key_columns_list.remove(i)

# COMMAND ----------

# Mapping the input data of brand to id
dict = {}

for i in gh_sku_mapping_df.collect():
  dict[i[0].lower()] = i[1]


# Mapping sku_desc with id from gh_sku_mapping_raw table to a new column temp and then renaming to sku_desc
mapping_expr = create_map([lit(x) for x in chain(*dict.items())])
gh_master_data_df = gh_master_data_df.withColumn('temp', mapping_expr[lower(gh_master_data_df.brand)])
gh_master_data_df = gh_master_data_df.drop('brand')
gh_master_data_df = gh_master_data_df.withColumnRenamed('temp','brand')


# COMMAND ----------

# create Key column by concatinating the key_columns list items
gh_master_data_df = gh_master_data_df.withColumn('Key',concat_ws("-",*key_columns_list))


# COMMAND ----------

# Volume data imputation
gh_master_data_df = gh_master_data_df.na.fill(0,subset=['volume_revised'])

gh_master_data_df = gh_master_data_df.withColumn('volume_revised',when(gh_master_data_df.volume_revised <0,0).otherwise(gh_master_data_df.volume_revised))

# COMMAND ----------

# Extracting data and merging month year to have date column
#gh_master_data_df = gh_master_data_df.withColumnRenamed('month','month')
gh_master_data_df.createOrReplaceTempView('gh_volume_sku')
gh_master_data_df = spark.sql("select concat(year,'-',right(month,2),'-','01') as Date, Key, sum(volume_revised) as Volume from gh_volume_sku group by Date, Key")

gh_master_data_df = gh_master_data_df.withColumn('Date', to_date(col("Date"), "yyyy-MM-dd"))
gh_master_data_df = gh_master_data_df.withColumn('Volume', gh_master_data_df['Volume'].cast(DoubleType()))
#gh_master_data_df = gh_master_data_df.withColumnRenamed('Volume','y')


# COMMAND ----------

# Taking keys which are not null
gh_master_data_df=gh_master_data_df.filter(gh_master_data_df.Key!='')


# COMMAND ----------

# creating key level volume and regressor data
new_column_reg = [f"{c.lower()}" for c in gh_feature_data_df.columns]
new_column_volume = [f"{c.lower()}" for c in gh_master_data_df.columns]
gh_feature_data_df = gh_feature_data_df.toDF(*new_column_reg)
gh_master_data_df = gh_master_data_df.toDF(*new_column_volume)

# COMMAND ----------

#display(gh_feature_data_df)

# COMMAND ----------

spark.sql(f"Drop table if exists {db_environment}.gh_master_data_preProc")
gh_master_data_df.write.format("parquet").saveAsTable(f"{db_environment}.gh_master_data_preProc")

spark.sql(f"Drop table if exists {db_environment}.gh_feature_data_preProc")
gh_feature_data_df.write.format("parquet").saveAsTable(f"{db_environment}.gh_feature_data_preProc")

# COMMAND ----------
