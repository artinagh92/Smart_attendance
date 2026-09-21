import sqlite3
import pandas as pd


db=sqlite3.connect(
"attendance.db"
)


query="""

SELECT *
FROM attendance

"""


data=pd.read_sql_query(
query,
db
)


data.to_excel(
"attendance_report.xlsx",
index=False
)


print(
"Report Created"
)