import mimetypes
import pandas as pd
from math import ceil
from typing import List
import random
import numpy as np
import json


from shiny import App, reactive, render, session, ui
from shiny.types import FileInfo

app_ui = ui.page_fluid(
    #Title
    ui.h2("Text Replay with Shiny"),

    #Sidebar for Controls and Main
    ui.layout_sidebar(
        #Define Sidebar Panel
        ui.sidebar(
            ui.input_file("file_upload", "Upload your dataset (CSV)", accept=[".csv"]),
            # Radio buttons to select the file separator
            ui.input_radio_buttons(
                "separator", "File Separator:",
                choices={"_comma": "Comma (,)", "_tab": "Tab (\\t)"},
                selected="_comma",
                inline=True
            ),
            #Dynamic UI Outpus for column selection dropdowns
            # These will be generated on the server side after a file is uploaded.
            ui.output_ui("column_selectors_ui"),
            #Dynamic UI for Filtering Controls
            ui.hr(),
            ui.h4("Filter and Navigate"),
            ui.output_ui("filter_selectors_ui"),
            ui.input_action_button("random_chunk_button","Surprise Me!", class_="btn-info w-100"),       
            # Text input for the user to name the tag they are creating
            ui.hr(),
        ),
        # Define the main content panel
#       # UI for navigation controls (previous/next buttons)   
        ui.row(
            ui.column(6, ui.input_action_button("prev_chunk", "Previous Chunk", class_="btn-sm")),
            ui.column(6, ui.input_action_button("next_chunk", "Next Chunk", class_="btn-sm")),
        ),

        ui.hr(),
        # Display the data table where users can select rows
        ui.output_ui("data_chunk_ui"),
        
        ui.hr(),
        ui.input_text("tag_name", "Tag Name:"),
        ui.input_action_button("tag_button", "Tag Selected Lines", class_="btn-primary"),

        ui.hr(),
        ui.output_ui("tagged_summary"),
        ui.download_button("downloadcoded","Download Coded Data", class_="btn-success w-100 mt-2")
        )
#    ),
    )

# Define the server-side logic of the application
def server(input, output, session):
    # --- Reactive Values for State Management ---

    # Stores the uploaded DataFrame.
    data = reactive.Value(None)
    # Stores the complete, unfiltered list of data groups.
    all_player_level_groups = reactive.Value([])
    # Stores the currently visible (potentially filtered) groups.
    player_level_groups = reactive.Value([])
    # Stores the indices of tagged rows.
    tagged_rows = reactive.Value({})
    # Tracks the current group index within the filtered list.
    current_group_index = reactive.Value(0)
    # Tracks the current 25-row chunk within a group.
    current_sub_chunk_index = reactive.Value(0)

    # --- Effects and Outputs ---

    @reactive.Effect
    @reactive.event(input.file_upload)
    def _handle_file_upload():
        """
        This function is triggered when a new file is uploaded.
        It reads the CSV file into a pandas DataFrame and resets the app's state.
        """
        f: list[FileInfo] = input.file_upload()
        if f:
            sep_char = ',' if input.separator() == '_comma' else '\t'
            try:
                df = pd.read_csv(f[0]["datapath"], sep=sep_char)
                df['original_index'] = df.index
                data.set(df)
                # Reset all state variables
                all_player_level_groups.set([])
                player_level_groups.set([])
                tagged_rows.set({})
                current_group_index.set(0)
                current_sub_chunk_index.set(0)
                print("File uploaded and DataFrame created.")
                ui.notification_show("File uploaded successfully!", duration=4)
            except Exception as e:
                ui.notification_show(f"Error parsing file: {e}", duration=10, type="error")
                data.set(None)

    @output
    @render.ui
    def column_selectors_ui():
        """Dynamically generates the UI for selecting the 'player' and 'level' columns."""
        if data() is not None:
            df = data()
            cols = [col for col in df.columns if col != 'original_index']
            return ui.div(
                ui.input_select("player_col", "Select Player Column", choices=cols, selected=cols[3] if cols else None),
                ui.input_select("level_col", "Select Level Column (optional)", choices=["None"] + cols, selected="None"),
                ui.input_select("text_col", "Seelect Text Column", choices=cols),
            )

    @reactive.Effect
    @reactive.event(input.player_col, input.level_col)
    def _group_data():
        """Groups the DataFrame when player/level columns are selected."""
        if data() is not None and input.player_col():
            df = data()
            player_col = input.player_col()
            level_col = input.level_col()
            group_by_cols = [player_col]
            if level_col and level_col != "None":
                group_by_cols.append(level_col)
            
            grouped = list(df.groupby(group_by_cols))
            all_player_level_groups.set(grouped)
            # Initially, the displayed groups are all the groups
            player_level_groups.set(grouped)
            current_group_index.set(0)
            current_sub_chunk_index.set(0)
            print(f"Data grouped by {group_by_cols}. Found {len(grouped)} groups.")
    
    @output
    @render.ui
    def filter_selectors_ui():
        """Dynamically generates the filtering dropdowns once data is grouped."""
        if not all_player_level_groups():
            return
        
        groups = all_player_level_groups()
        player_col = input.player_col()
        level_col = input.level_col()

        # Extract unique player names
        players = sorted(list(set(g[0][0] if isinstance(g[0], tuple) else g[0] for g in groups)))

        # Extract unique level names if a level column is selected
        levels = []
        if level_col and level_col != "None":
            levels = sorted(list(set(g[0][1] for g in groups if isinstance(g[0], tuple) and len(g[0]) > 1)))

        return ui.div(
            ui.input_select("filter_player", "Filter by Player", choices=["All"] + players, selected="All"),
            ui.input_select("filter_level", "Filter by Level", choices=["All"] + levels, selected="All") if levels else None
        )

    @reactive.Effect
    def _apply_filters():
        """Filters the groups based on dropdown selections."""
        groups = all_player_level_groups()
        player_filter = input.filter_player()
        level_filter = input.filter_level()
        level_col = input.level_col()

        if not groups:
            return

        filtered = groups
        # Filter by player
        if player_filter and player_filter != "All":
            filtered = [g for g in filtered if (g[0][0] if isinstance(g[0], tuple) else g[0]) == player_filter]
        
        # Filter by level
        if level_col and level_col != "None" and level_filter and level_filter != "All":
            filtered = [g for g in filtered if isinstance(g[0], tuple) and len(g[0]) > 1 and g[0][1] == level_filter]
            
        player_level_groups.set(filtered)
        current_group_index.set(0)
        current_sub_chunk_index.set(0)

    @reactive.Calc
    def current_chunk_data():
        """Calculates the current 25-row data chunk to display."""
        if not player_level_groups():
            return None, None
        group_idx = current_group_index.get()
        if group_idx >= len(player_level_groups()):
            return None, "End of filtered groups."
        group_name, group_df = player_level_groups()[group_idx]
        sub_chunk_idx = current_sub_chunk_index.get()
        start_row = sub_chunk_idx * 25
        end_row = start_row + 25
        chunk_df = group_df.iloc[start_row:end_row]
        info_text = f"Displaying Group: {group_name} (Rows {start_row+1}-{end_row}) | Group {group_idx + 1} of {len(player_level_groups())}"
        return chunk_df, info_text

    @output
    @render.ui
    def data_chunk_ui():
        """Renders the data table with checkboxes."""
        chunk_df, _ = current_chunk_data()
        if chunk_df is None or chunk_df.empty:
            return ui.p("No data to display. Upload a file, select columns, or adjust filters.")
        #checkboxes = [ui.input_checkbox(f"tag_row_{original_idx}", "") for original_idx in chunk_df['original_index']]
        #display_df.insert(0, "Select", checkboxes)
        checkbox_choices = {};
        for index, row in chunk_df.iterrows():
            checkbox_choices[str(index)] = ui.span(row[input.text_col()])
        return ui.div(
            ui.input_checkbox_group(
                "chunk_checkboxes",
                "Select entries that apply",
                checkbox_choices,
            )
        )
    
    @output
    @render.text()
    def test_checkboxes():
        return "Selected indices: " + ", ".join(input.chunk_checkboxes())

    @reactive.Effect
    @reactive.event(input.tag_button)
    def _tag_selected_lines():
        tag = input.tag_name()
        selected_chunk_indices = set(input.chunk_checkboxes())
        current_tags = tagged_rows.get()

        if tag not in current_tags:
            current_tags[tag] = {}

        chunk_df, _ = current_chunk_data()
        for index, row in chunk_df.iterrows():
            current_tags[tag][index] = str(index) in selected_chunk_indices

        tagged_rows.unset()
        tagged_rows.set(current_tags)

    @reactive.Effect
    @reactive.event(input.random_chunk_button)
    def _go_to_random_chunk():
        """Jumps to a random group and a random sub-chunk."""
        if not player_level_groups():
            ui.notification_show("No data to select from.", duration=3)
            return
        
        # Select a random group
        random_group_idx = random.randint(0, len(player_level_groups()) - 1)
        _, group_df = player_level_groups()[random_group_idx]
        
        # Select a random sub-chunk within that group
        max_sub_chunk = (len(group_df) - 1) // 25
        random_sub_chunk_idx = random.randint(0, max_sub_chunk)
        
        current_group_index.set(random_group_idx)
        current_sub_chunk_index.set(random_sub_chunk_idx)
        ui.notification_show("Jumped to a random selection!", duration=3)

    @reactive.Effect
    @reactive.event(input.next_chunk)
    def _go_to_next_chunk():
        """Handles the logic for the 'Next Chunk' button."""
        if not player_level_groups(): return
        group_idx = current_group_index.get()
        sub_chunk_idx = current_sub_chunk_index.get()
        _, group_df = player_level_groups()[group_idx]
        if (sub_chunk_idx + 1) * 25 < len(group_df):
            current_sub_chunk_index.set(sub_chunk_idx + 1)
        elif group_idx + 1 < len(player_level_groups()):
            current_group_index.set(group_idx + 1)
            current_sub_chunk_index.set(0)
        else:
            ui.notification_show("You have reached the end of the dataset.", duration=3)

    @reactive.Effect
    @reactive.event(input.prev_chunk)
    def _go_to_prev_chunk():
        """Handles the logic for the 'Previous Chunk' button."""
        sub_chunk_idx = current_sub_chunk_index.get()
        group_idx = current_group_index.get()
        if sub_chunk_idx > 0:
            current_sub_chunk_index.set(sub_chunk_idx - 1)
        elif group_idx > 0:
            new_group_idx = group_idx - 1
            current_group_index.set(new_group_idx)
            _, prev_group_df = player_level_groups()[new_group_idx]
            last_sub_chunk = (len(prev_group_df) - 1) // 25
            current_sub_chunk_index.set(last_sub_chunk)
        else:
            ui.notification_show("You are at the beginning of the dataset.", duration=3)

    def getTagSummary(tag, tagged_indices):
        total = len(tagged_indices)
        selected = len(list(filter(lambda v: v, tagged_indices.values())))
        return ui.tags.li(f"'{tag}': {total} total rows, {selected} selected")

    @output
    @render.text
    def tagged_summary():
        """Renders a summary of all tagged rows."""
        tags = tagged_rows()
        if not tags:
            return "No rows have been tagged yet."
        summary_list = [getTagSummary(tag, indices) for tag, indices in tags.items()]
        return ui.tags.ul(summary_list)
    
    @session.download(
        filename="Codes.csv"
    )
    def downloadcoded():
        tags_dict = tagged_rows()
        dfOut = data()

        if dfOut is None or not tags_dict:
            ui.notification_show("No data to download.", duration=10, type="warning")
            return

        all_tagged_indices = set()
        for indices_dict in tags_dict.values():
            all_tagged_indices.update(indices_dict.keys())

        if not all_tagged_indices:
            ui.notification_show("No rows have been tagged to download.", duration=4, type="warning")
            return
        
        for tag_name, indices_dict in tags_dict.items():
            dfOut[tag_name] = dfOut.index.map(lambda idx: indices_dict.get(idx, False))

        yield dfOut.to_csv(index=True)

# Create the Shiny app instance
app = App(app_ui, server)