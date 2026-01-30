from cProfile import label
from enum import show_flag_values
from sys import prefix
from altair import value
import pandas as pd
import streamlit as st
import os
from sqlmodel import Session, select, func
from src.models import Transaction, Campaign, Strategy, Note
from src.dbfunctions import create_engine_func
import plotly.graph_objects as go

def plot_metric(
        label,
        value,
        prefix="",
        suffix="",
        show_graph="",
):
    fig = go.Figure()
    fig.add_trace(
        go.Indicator(
            value=value,
            gauge={"axis":{"visible": False}},
            title={"text": label},
            number={"prefix": prefix, "suffix": suffix, "font": {"size": 48}},
        )
    )
    if show_graph:
        fig.add_trace(
            go.Scatter(
                x=[1,2,3,4,5,6,7,8,9,10],
                y=[2,3,5,4,9,5,7,8,7,9],
                mode="lines",
                line=dict(color="ivory"),
                showlegend=False,
                hoverinfo="skip",
                fill="tozeroy",
                fillcolor="#ff0000",
            )
        )
    fig.update_xaxes(visible=False, fixedrange=True)
    fig.update_yaxes(visible=False, fixedrange=True)
    fig.update_layout(
        margin=dict(t=40, b=0),
        showlegend=False,
        plot_bgcolor="white",
        height=100,
        #margin=dict(t=20, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)

def plot_gauge(
        indicator_number,
        indicator_color,
        indicator_suffix,
        indicator_title,
        max_bound,
):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=indicator_number,
            domain={"x":[0,1],"y":[0,1]},
            number={"suffix": indicator_suffix, "font": {"size": 36}},
            title={"text": indicator_title, "font": {"size": 24}},
            gauge={
                "axis": {"range": [0, max_bound]},
                "bar": {"color": indicator_color},
                "steps": [
                    {"range": [0, max_bound * 0.5], "color": "#c0c0c0"},
                    {"range": [max_bound * 0.5, max_bound], "color": "#c0c0c0"},
                ],
            },
        )
    )
    fig.update_layout(
        height=300,
        margin=dict(t=20, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)

# 1. Setup the Database Connection
db_url = "sqlite:///data/portfolio.db"
engine = create_engine_func(db_url)
adjusted_cost_basis = 0
total_debits = 0

# 2. Open the Session
with Session(engine) as session:
    # A. Find the Campaign by Name
    # (Replace "ASTS Wheel" with your exact campaign name)
    target_campaign_name = "ASTS - ASTS Wheel" 
    
    #campaign = session.exec(
    #    select(Campaign).where(Campaign.name == target_campaign_name)
    #).first()
    campaign = session.exec(select(Campaign)).first()

    if not campaign:
        print(f"❌ Could not find campaign: '{target_campaign_name}'")
    else:
        print(f"✅ Found Campaign: {campaign.name} (ID: {campaign.id})")

        # B. Get the Trades
        # Logic: Select * FROM Transaction WHERE campaign_id = X
        trades = session.exec(
            select(Transaction)
            .where(Transaction.campaign_id == campaign.id)
            .order_by(Transaction.exec_date)
        ).all()

        print(f"   Found {len(trades)} transactions.")

        # 3. Calculate Adjusted Cost Basis
        # In your DB: 
        #   Negative cb_amount = Money OUT (Buying Stock/Options)
        #   Positive cb_amount = Money IN (Selling Puts/Calls)
        
        # Net Cash Flow = (Premiums Collected) - (Cost of Shares)
        net_cash_flow = sum(t.cb_amount for t in trades)
        
        # Adjusted Basis is essentially your "Net Debit"
        # If Net Cash Flow is -$500, your Basis is $500.
        # If Net Cash Flow is +$200, your Basis is -$200 (Free riding!)
        adjusted_cost_basis = -net_cash_flow

        print("-" * 30)
        print(f"💰 Net Cash Flow:      ${net_cash_flow:,.2f}")
        print(f"📉 Adjusted Cost Basis: ${adjusted_cost_basis:,.2f}")

        # Optional: Breakdown for the Gauge
        total_debits = sum(abs(t.cb_amount) for t in trades if t.cb_amount < 0)
        total_credits = sum(t.cb_amount for t in trades if t.cb_amount > 0)
        
        print(f"   Total Spent (Basis): ${total_debits:,.2f}")
        print(f"   Total Collected:     ${total_credits:,.2f}")


fig = go.Figure(go.Indicator(
    mode = "gauge+number+delta",
    value = adjusted_cost_basis,  # The value we calculated above
    domain = {'x': [0, 1], 'y': [0, 1]},
    title = {'text': "Adjusted Cost Basis"},
    delta = {'reference': total_debits, 'increasing': {'color': "red"}, 'decreasing': {'color': "green"}},
    gauge = {
        'axis': {'range': [0, total_debits]}, # Max range is the original cost
        'bar': {'color': "#2E86C1"}, # Your nice blue color
        'steps': [
            {'range': [0, total_debits], 'color': "lightgray"} 
        ],
    }
))
st.plotly_chart(fig)

plot_metric(
    label="ASTS Adj Cost Basis",
    value=1000,
    prefix="$",
    suffix="",
    show_graph="",
    #show_graph="yes"
)
plot_gauge(
    indicator_number=1.5,
    indicator_color="Blue",
    indicator_suffix="%",
    indicator_title="ASTS Return",
    max_bound=3,
)