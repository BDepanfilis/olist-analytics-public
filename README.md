\# Olist Analytics (Public App)



This repo contains the Streamlit app only. The DuckDB snapshot lives in a \*\*private\*\* repo and is fetched at runtime from a GitHub Release.



\## Deploy on Streamlit Cloud



1\. Fork/clone this repo.

2\. In Streamlit Cloud, set \*\*Secrets\*\*:

&nbsp;  ```toml

&nbsp;  \[github]

&nbsp;  owner = "BDePanfilis"

&nbsp;  repo = "Olist-DB-Private"

&nbsp;  asset\_name = "olist.duckdb"

&nbsp;  tag = "latest"

&nbsp;  token = "YOUR\_GITHUB\_PAT\_WITH\_REPO\_READ"



