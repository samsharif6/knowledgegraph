import math
import html
from typing import Any, Dict, List, Tuple

import networkx as nx
import requests
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

st.set_page_config(
    page_title="OpenAlex Dataset Explorer",
    page_icon="🔍",
    layout="wide",
)

OPENALEX_BASE = "https://api.openalex.org"
REQUEST_TIMEOUT = 30

COLORS = {
    "dataset": "#FF6B6B",
    "paper": "#B19CD9",
    "author": "#4DABF7",
    "institution": "#69DB7C",
    "funder": "#FCC419",
}


def api_get_json(url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    headers = {
        "User-Agent": "streamlit-openalex-explorer/1.0",
    }
    response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def build_citation(work_data: Dict[str, Any]) -> str:
    authorships = work_data.get("authorships", [])
    author_names = [
        a.get("author", {}).get("display_name")
        for a in authorships
        if a.get("author", {}).get("display_name")
    ]

    if len(author_names) > 3:
        author_str = f"{author_names[0]}, {author_names[1]}, et al."
    elif author_names:
        author_str = ", ".join(author_names)
    else:
        author_str = "Unknown Authors"

    year = work_data.get("publication_year") or "n.d."
    title = work_data.get("title") or "Untitled"

    source_name = ""
    primary_loc = work_data.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    if source.get("display_name"):
        source_name = f". {source.get('display_name')}"

    return f"{author_str} ({year}). {title}{source_name}."


def extract_author_profile(auth_data: Dict[str, Any]) -> Dict[str, Any]:
    h_index = auth_data.get("summary_stats", {}).get("h_index", 0)
    citations = auth_data.get("cited_by_count", 0)
    works_count = auth_data.get("works_count", 0)

    insts = auth_data.get("last_known_institutions", [])
    institution = insts[0].get("display_name") if insts else "Institution Not Listed"

    concepts = auth_data.get("x_concepts", [])
    field = concepts[0].get("display_name") if concepts else "General Science"

    return {
        "h_index": h_index,
        "citations": citations,
        "works": works_count,
        "inst": institution,
        "field": field,
    }


def html_tooltip(title: str, body_lines: List[str]) -> str:
    safe_lines = [html.escape(str(line)) for line in body_lines if line is not None]
    joined = "<br>".join(safe_lines)
    return f"<b>{html.escape(title)}</b><hr>{joined}"


@st.cache_data(show_spinner=False, ttl=3600)
def search_datasets(keyword: str, per_page: int = 50) -> List[Tuple[str, str]]:
    params = {
        "filter": "type:dataset,institutions.country_code:AU",
        "per-page": per_page,
        "sort": "cited_by_count:desc",
    }
    if keyword.strip():
        params["search"] = keyword.strip()

    data = api_get_json(f"{OPENALEX_BASE}/works", params=params)
    options: List[Tuple[str, str]] = []
    for work in data.get("results", []):
        work_id = work.get("id", "")
        if not work_id:
            continue
        dataset_id = work_id.split("/")[-1]
        title = work.get("title") or "Untitled"
        year = work.get("publication_year", "N/A")
        display_text = f"{title[:90]}{'...' if len(title) > 90 else ''} ({year})"
        options.append((display_text, dataset_id))
    return options


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_author_profiles(author_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not author_ids:
        return {}

    author_ids_str = "|".join(author_ids[:50])
    authors_url = f"{OPENALEX_BASE}/authors"
    authors_data = api_get_json(authors_url, params={"filter": f"openalex:{author_ids_str}"})

    profiles: Dict[str, Dict[str, Any]] = {}
    for auth in authors_data.get("results", []):
        profiles[auth.get("id")] = extract_author_profile(auth)
    return profiles


@st.cache_data(show_spinner=False, ttl=3600)
def build_graph_html(dataset_id: str) -> Tuple[str, Dict[str, int], str]:
    dataset_url = f"{OPENALEX_BASE}/works/{dataset_id}"
    work = api_get_json(dataset_url)
    G = nx.Graph()

    dataset_title = work.get("title") or "Untitled Dataset"
    dataset_citations = work.get("cited_by_count", 0)
    short_title = dataset_title[:40] + "..." if len(dataset_title) > 40 else dataset_title
    dataset_node_size = 20 + (math.sqrt(dataset_citations) * 3)

    dataset_hover = html_tooltip(
        "DATASET",
        [build_citation(work), "", f"Citations: {dataset_citations:,}"],
    )
    G.add_node(
        dataset_id,
        label=short_title,
        title=dataset_hover,
        size=dataset_node_size,
        group="Dataset",
        font={"color": "white", "size": 16, "face": "arial"},
    )

    core_author_ids = [
        auth.get("author", {}).get("id", "").split("/")[-1]
        for auth in work.get("authorships", [])
        if auth.get("author", {}).get("id")
    ]
    author_profiles = fetch_author_profiles(core_author_ids)

    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        author_id = author.get("id")
        author_name = author.get("display_name") or "Unknown"

        if author_id:
            profile = author_profiles.get(author_id, {})
            auth_h_index = profile.get("h_index", 0)
            author_node_size = 10 + (auth_h_index * 1.2)
            author_hover = html_tooltip(
                "AUTHOR",
                [
                    author_name,
                    profile.get("inst", ""),
                    "",
                    f"Primary Field: {profile.get('field', 'N/A')}",
                    f"h-index: {auth_h_index} | Total Works: {profile.get('works', 0)}",
                    f"Total Citations: {profile.get('citations', 0):,}",
                ],
            )
            G.add_node(
                author_id,
                label=author_name,
                title=author_hover,
                size=author_node_size,
                group="Author",
            )
            G.add_edge(dataset_id, author_id, color="#555555", width=2)

        for inst in authorship.get("institutions", []):
            inst_id = inst.get("id")
            inst_name = inst.get("display_name") or "Unknown institution"
            if inst_id:
                G.add_node(
                    inst_id,
                    label=inst_name,
                    title=html_tooltip("INSTITUTION", [inst_name]),
                    size=20,
                    shape="box",
                    group="Institution",
                )
                if author_id:
                    G.add_edge(author_id, inst_id, color="#555555", width=2)

    for grant in work.get("grants", []):
        funder_id = grant.get("funder")
        funder_name = grant.get("funder_display_name", "Unknown Funder")
        if funder_id:
            f_id = funder_id.split("/")[-1]
            if not G.has_node(f_id):
                G.add_node(
                    f_id,
                    label=funder_name[:25],
                    title=html_tooltip("FUNDER", [funder_name]),
                    size=20,
                    group="Funder",
                )
            G.add_edge(dataset_id, f_id, color="#555555", width=2, dashes=True)

    citing_data = api_get_json(
        f"{OPENALEX_BASE}/works",
        params={
            "filter": f"cites:{dataset_id}",
            "sort": "cited_by_count:desc",
            "per-page": 5,
        },
    )

    hop2_edges: List[Tuple[str, str]] = []
    hop2_author_ids: set[str] = set()
    hop2_author_names: Dict[str, str] = {}

    for paper in citing_data.get("results", []):
        paper_id = paper.get("id")
        if not paper_id:
            continue

        paper_title = paper.get("title") or "Untitled Paper"
        paper_citations = paper.get("cited_by_count", 0)
        paper_node_size = 10 + (math.sqrt(paper_citations) * 1.5)

        G.add_node(
            paper_id,
            label=(paper_title[:30] + "...") if len(paper_title) > 30 else paper_title,
            title=html_tooltip(
                "PAPER (Citing)",
                [build_citation(paper), "", f"Citations: {paper_citations:,}"],
            ),
            size=paper_node_size,
            group="Paper",
        )
        G.add_edge(dataset_id, paper_id, color="#555555", width=2)

        for authorship in paper.get("authorships", [])[:2]:
            p_author_id = authorship.get("author", {}).get("id")
            p_author_name = authorship.get("author", {}).get("display_name") or "Unknown"
            if p_author_id:
                hop2_edges.append((paper_id, p_author_id))
                hop2_author_ids.add(p_author_id.split("/")[-1])
                hop2_author_names[p_author_id] = p_author_name

        for grant in paper.get("grants", []):
            funder_id = grant.get("funder")
            funder_name = grant.get("funder_display_name", "Unknown Funder")
            if funder_id:
                f_id = funder_id.split("/")[-1]
                if not G.has_node(f_id):
                    G.add_node(
                        f_id,
                        label=funder_name[:25],
                        title=html_tooltip("FUNDER", [funder_name]),
                        size=15,
                        group="Funder",
                    )
                G.add_edge(paper_id, f_id, color="#444444", dashes=True, width=1)

    hop2_author_profiles = fetch_author_profiles(list(hop2_author_ids)) if hop2_author_ids else {}

    for paper_id, p_author_id in hop2_edges:
        if not G.has_node(p_author_id):
            profile = hop2_author_profiles.get(p_author_id, {})
            h2_h_index = profile.get("h_index", 0)
            h2_size = 8 + (h2_h_index * 0.8)
            p_author_name = hop2_author_names.get(p_author_id, "Unknown")
            G.add_node(
                p_author_id,
                label=p_author_name,
                title=html_tooltip(
                    "AUTHOR (Citing)",
                    [
                        p_author_name,
                        profile.get("inst", ""),
                        "",
                        f"Primary Field: {profile.get('field', 'N/A')}",
                        f"h-index: {h2_h_index} | Total Works: {profile.get('works', 0)}",
                        f"Total Citations: {profile.get('citations', 0):,}",
                    ],
                ),
                size=h2_size,
                group="Author",
            )
        G.add_edge(paper_id, p_author_id, color="#444444", dashes=True, width=1)

    for auth_id in core_author_ids[:3]:
        author_works_data = api_get_json(
            f"{OPENALEX_BASE}/works",
            params={
                "filter": f"author.id:{auth_id}",
                "sort": "cited_by_count:desc",
                "per-page": 3,
            },
        )
        for auth_paper in author_works_data.get("results", []):
            ap_id = auth_paper.get("id")
            if not ap_id or ap_id == dataset_id:
                continue

            if not G.has_node(ap_id):
                ap_title = auth_paper.get("title") or "Untitled"
                ap_citations = auth_paper.get("cited_by_count", 0)
                ap_size = 10 + (math.sqrt(ap_citations) * 1.5)
                G.add_node(
                    ap_id,
                    label=(ap_title[:30] + "...") if len(ap_title) > 30 else ap_title,
                    title=html_tooltip(
                        "PAPER",
                        [build_citation(auth_paper), "", f"Citations: {ap_citations:,}"],
                    ),
                    size=ap_size,
                    group="Paper",
                )

            G.add_edge(f"https://openalex.org/{auth_id}", ap_id, color="#444444", dashes=True, width=1)

            for grant in auth_paper.get("grants", []):
                funder_id = grant.get("funder")
                funder_name = grant.get("funder_display_name", "Unknown Funder")
                if funder_id:
                    f_id = funder_id.split("/")[-1]
                    if not G.has_node(f_id):
                        G.add_node(
                            f_id,
                            label=funder_name[:25],
                            title=html_tooltip("FUNDER", [funder_name]),
                            size=15,
                            group="Funder",
                        )
                    G.add_edge(ap_id, f_id, color="#444444", dashes=True, width=1)

    net = Network(
        height="820px",
        width="100%",
        bgcolor="#1E1E24",
        font_color="white",
        cdn_resources="remote",
    )
    net.from_nx(G)

    options_str = f"""
    var options = {{
      "groups": {{
        "Dataset": {{ "color": "{COLORS['dataset']}" }},
        "Author": {{ "color": "{COLORS['author']}" }},
        "Institution": {{ "color": "{COLORS['institution']}" }},
        "Funder": {{ "color": "{COLORS['funder']}" }},
        "Paper": {{ "color": "{COLORS['paper']}" }}
      }},
      "nodes": {{
        "borderWidth": 0,
        "shadow": {{"enabled": true, "color": "rgba(0,0,0,0.5)", "size": 10}},
        "font": {{"color": "#FFFFFF"}}
      }},
      "edges": {{
        "smooth": {{"type": "continuous", "roundness": 0.5}}
      }},
      "physics": {{
        "barnesHut": {{
          "gravitationalConstant": -4000,
          "centralGravity": 0.3,
          "springLength": 250
        }},
        "minVelocity": 0.75
      }}
    }}
    """
    net.set_options(options_str)

    raw_html = net.generate_html()
    custom_ui = f"""
    <style>
      .vis-tooltip {{
          background-color: rgba(30, 30, 36, 0.95) !important;
          border: 1px solid #555 !important;
          border-radius: 8px !important;
          color: white !important;
          padding: 12px !important;
          max-width: 360px !important;
      }}
      .vis-tooltip hr {{ border-color: #555; margin: 8px 0; }}
    </style>
    <div style="position: absolute; bottom: 30px; left: 30px; z-index: 9999; background: rgba(30, 30, 36, 0.9); padding: 15px; border-radius: 8px; color: white; border: 1px solid #555; font-family: sans-serif; box-shadow: 2px 2px 10px rgba(0,0,0,0.5);">
        <h4 style="margin-top: 0; margin-bottom: 10px; border-bottom: 1px solid #555; padding-bottom: 5px;">Filter Map</h4>
        <label style="display: block; margin-bottom: 5px; cursor: pointer;"><input type="checkbox" checked onchange="toggleGroup('Author', this.checked)"> Authors <span style="color:{COLORS['author']}">●</span></label>
        <label style="display: block; margin-bottom: 5px; cursor: pointer;"><input type="checkbox" checked onchange="toggleGroup('Institution', this.checked)"> Institutions <span style="color:{COLORS['institution']}">■</span></label>
        <label style="display: block; margin-bottom: 5px; cursor: pointer;"><input type="checkbox" checked onchange="toggleGroup('Funder', this.checked)"> Funders <span style="color:{COLORS['funder']}">●</span></label>
        <label style="display: block; cursor: pointer;"><input type="checkbox" checked onchange="toggleGroup('Paper', this.checked)"> Papers <span style="color:{COLORS['paper']}">●</span></label>
    </div>
    <script>
    function toggleGroup(groupName, isVisible) {{
        if (typeof nodes === 'undefined') return;
        var updateArray = [];
        var allNodes = nodes.get();
        for (var i = 0; i < allNodes.length; i++) {{
            if (allNodes[i].group === groupName) {{
                updateArray.push({{id: allNodes[i].id, hidden: !isVisible}});
            }}
        }}
        nodes.update(updateArray);
    }}
    </script>
    """
    html_content = raw_html.replace("<body>", f"<body>{custom_ui}")

    stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "authors": sum(1 for _, data in G.nodes(data=True) if data.get("group") == "Author"),
        "papers": sum(1 for _, data in G.nodes(data=True) if data.get("group") == "Paper"),
        "institutions": sum(1 for _, data in G.nodes(data=True) if data.get("group") == "Institution"),
        "funders": sum(1 for _, data in G.nodes(data=True) if data.get("group") == "Funder"),
    }
    return html_content, stats, dataset_title


def main() -> None:
    st.title("🔍 OpenAlex Dataset Knowledge Graph Explorer")
    st.caption("Search Australian datasets in OpenAlex and generate an interactive relationship graph.")

    with st.sidebar:
        st.header("Search")
        keyword = st.text_input(
            "Keyword",
            placeholder="Type a keyword like climate, health, reef...",
        )
        run_search = st.button("Find datasets", use_container_width=True)

    if "search_results" not in st.session_state:
        st.session_state.search_results = []
    if "selected_dataset_id" not in st.session_state:
        st.session_state.selected_dataset_id = None

    if run_search:
        try:
            with st.spinner("Searching OpenAlex..."):
                st.session_state.search_results = search_datasets(keyword)
            if not st.session_state.search_results:
                st.warning("No datasets found for that keyword. Try another search term.")
        except requests.HTTPError as exc:
            st.error(f"OpenAlex request failed: {exc}")
        except Exception as exc:
            st.error(f"Something went wrong during search: {exc}")

    if st.session_state.search_results:
        labels = [label for label, _ in st.session_state.search_results]
        lookup = {label: value for label, value in st.session_state.search_results}

        selected_label = st.selectbox("Select a dataset", labels)
        st.session_state.selected_dataset_id = lookup[selected_label]

        if st.button("Generate knowledge graph", type="primary"):
            try:
                with st.spinner("Building the graph..."):
                    html_content, stats, dataset_title = build_graph_html(st.session_state.selected_dataset_id)

                st.subheader(dataset_title)
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("Nodes", stats["nodes"])
                c2.metric("Edges", stats["edges"])
                c3.metric("Authors", stats["authors"])
                c4.metric("Papers", stats["papers"])
                c5.metric("Institutions", stats["institutions"])
                c6.metric("Funders", stats["funders"])

                components.html(html_content, height=860, scrolling=True)
            except requests.HTTPError as exc:
                st.error(f"OpenAlex request failed while building the graph: {exc}")
            except Exception as exc:
                st.error(f"Something went wrong while building the graph: {exc}")
    else:
        st.info("Search for a keyword to load datasets.")

    with st.expander("About this tool"):
        st.markdown(
            """
            This is a demonstration developed by the **Translational Research Data Challenges (TRDC) team** to explore how knowledge graphs can be generated around research datasets using OpenAlex data.
    
            **Disclaimer:**  
            This is a prototype. Data and relationships are dynamically generated and may be incomplete or inaccurate. The outputs are indicative only and should not be used for decision-making without further validation.
            """
        )


if __name__ == "__main__":
    main()
