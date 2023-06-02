#import packages

import datetime
import streamlit as st
import jpholiday
from dateutil import relativedelta
import requests
import json
import pandas as pd   
from pandas_datareader import data as pdr
import mplfinance as mpf
import talib as ta
import yfinance as yf
yf.pdr_override()
import warnings
warnings.simplefilter('ignore')

st.set_option('deprecation.showPyplotGlobalUse', False)

#Global variable session state (are keeped)
User_email = 'your email'


#Function(session state)

def Initialize_states(pair:dict):
    for key, value in pair.items():
        if key not in st.session_state:
            st.session_state[key] = value




init_value = {
               'button_Get_API_Data': False,
               'button_Screening': False,
               'headers': dict(),
               'df_JQprices': pd.DataFrame(),
               'df_JQinfo': pd.DataFrame(),
               'JQ_code': pd.Series(),
               'df_Yprices': pd.DataFrame(),
               'df_technical': pd.DataFrame(),
               'code_screened':list()
            }


Initialize_states(init_value)




#function(backend)=========================================================================================================

#土日祝日の場合はtodayを直近の平日に変換する関数を定義 = NearBizday(someday)
def NearBizday(someday:datetime):
    while (someday.weekday() >=5 or jpholiday.is_holiday(someday)):               # 0=月, 1=火～4=金,5=土,6=日
        someday -= datetime.timedelta(days=1)
    
    return someday


#J-Quants APIからの情報取得 
def get_APIkey(mailaddress:str, password:str):

    #refresh token取得 = REFRESH_TOKEN
    try:
        res = requests.post("https://api.jquants.com/v1/token/auth_user", data=json.dumps({"mailaddress":mailaddress, "password":password}))
        REFRESH_TOKEN = res.json()['refreshToken']

    except:
        return False
    else:
        #id tokenの取得 = ID_TOKEN
        try:
            res = requests.post(f"https://api.jquants.com/v1/token/auth_refresh?refreshtoken={REFRESH_TOKEN}")
            ID_TOKEN = res.json()['idToken']

        except: 
            return False

        else:
            st.session_state.headers = {'Authorization': 'Bearer {}'.format(ID_TOKEN)}
            return True
        
       


#直近営業日の上場全銘柄株価情報の取得 
def get_JQstocksPrice():

    #フリープランの場合、データは12週間以前のデータが取得可能
    Twelve_weeks_ago = NearBizday(datetime.date.today() - datetime.timedelta(weeks=12)) 

    try:
        res = requests.get(f"https://api.jquants.com/v1/prices/daily_quotes?date={Twelve_weeks_ago.strftime('%Y%m%d')}", headers=st.session_state.headers)
        data = res.json()['daily_quotes']
        st.session_state.df_JQprices = pd.DataFrame(data)

    except:
        return False
    
    else:
        st.session_state.df_JQprices.dropna()
        return True


#上場銘柄一覧の取得(/listed/info) 
def get_JQstocksInfo():

    res = requests.get("https://api.jquants.com/v1/listed/info", headers=st.session_state.headers)

    if res.status_code != 200:
        return False
    
    else:
        data = res.json()['info'] 
        st.session_state.df_JQinfo = pd.DataFrame(data)
        return True


 #銘柄コード一覧(Series)の作成 = JQ_code
def screening_code():

   
    #東証プライム(0111)、スタンダード(0112)、グロース(0113)をMarketCodeに持つデータのみ抽出　※ETF等削除
    df = st.session_state.df_JQinfo[st.session_state.df_JQinfo['MarketCode'].isin(['0111', '0112', '0113'])]
    df = df[df['Code'].astype(int)%10 == 0]

    #銘柄コードのシリーズに変換する
    code = pd.Series(df['Code'])
    code.dropna()

    #Codeを10で割り、銘柄コードを標準化する
    code = code.astype(int)/10
    code = code.astype(int).astype(str)

    #インデックスの再設定　　※drop=Trueはインデックスの上書き、inplace=Trueは元オブジェクトに更新を適用
    code.reset_index(drop=True, inplace=True)

    
    #出来高が100万を超える銘柄コードを抽出 = heavy_deal_code
    heavy_deal_prices = df[st.session_state.df_JQprices['Volume']>=Min_Volume*10000]
    heavy_deal_code = pd.Series(heavy_deal_prices['Code'])


    #Codeを10で割り、銘柄コードを標準化する
    heavy_deal_code = heavy_deal_code.astype(int)//10
    heavy_deal_code = heavy_deal_code.astype(str)

    #インデックスの再設定　　※drop=Trueはインデックスの上書き、inplace=Trueは元オブジェクトに更新を適用
    heavy_deal_code.reset_index(drop=True, inplace=True)

    #ETFを除く出来高100万以上の銘柄に限定（JQ_codeとheavy_deal_codeの重複列を抽出）= JQ_code
    st.session_state.JQ_code = heavy_deal_code[heavy_deal_code.isin(code)]

    #インデックスの再設定　　※drop=Trueはインデックスの上書き、inplace=Trueは元オブジェクトに更新を適用
    st.session_state.JQ_code.reset_index(drop=True, inplace=True)


    #過去2年分の株価データを取得 = df_Yprices

    nowadays = NearBizday(datetime.date.today())
    Two_years_ago = NearBizday(nowadays - relativedelta.relativedelta(years=2))

    df_Yprices =  pdr.get_data_yahoo(list(st.session_state.JQ_code +'.T'), Two_years_ago, nowadays + datetime.timedelta(days=1))   #当日分の収集は翌日を指定




    #過去2年分の株価データ（df_Yprices）に単純移動平均線、ボリンジャーバンド、ATRのデータを追加 = df_technical

    #df_Ypricesの終値(Closeカラム)から
    #銘柄(market_code:str)とその銘柄の株価データ(df_price:pd.Series)を抜き出しfor文で繰り返し処理

    #NAを含む列を削除して上書き
    close_Yprice = df_Yprices['Close']
    close_Yprice.dropna(axis=1, inplace=True)


    market_codes = []

    for market_code, df_price in close_Yprice.items():
        
        market_codes.append(market_code)
        
        #移動平均線の追加
        df_Yprices['SMA'+str(SMA_Short), market_code] = df_price.rolling(window=SMA_Short).mean()
        df_Yprices['SMA'+str(SMA_Median), market_code] = df_price.rolling(window=SMA_Median).mean()
        df_Yprices['SMA'+str(SMA_Long), market_code] = df_price.rolling(window=SMA_Long).mean()
        df_Yprices['SMA'+str(SMA_Vlong), market_code] = df_price.rolling(window=SMA_Vlong).mean()

        #ドンチャンチャネルの追加
        df_Yprices['Donchan_high'+str(Donchian_high_period), market_code] = df_price.rolling(window=Donchian_high_period).max()
        df_Yprices['Donchan_low'+str(Donchian_low_period), market_code] = df_price.rolling(window=Donchian_high_period).min()
        
        #ボリンジャーバンドの追加
        df_Yprices['BB_upper', market_code], df_Yprices['BB_middle', market_code], df_Yprices['BB_lower', market_code] \
        = ta.BBANDS(df_price, timeperiod=BB_Median_period, nbdevup=BB_sigma, nbdevdn=BB_sigma, matype=0)     #matype= 0:単純, 1:指数, 2:加重

        #MACDの追加
        df_Yprices['MACD', market_code],  df_Yprices['MACDsignal', market_code],  df_Yprices['MACDhist', market_code] \
        = ta.MACD(df_price, fastperiod=MACD_Fast_period, slowperiod=MACD_Slow_period, signalperiod=MACD_Signal_period)

        #RSIの追加
        df_Yprices['RSI', market_code] = ta.RSI(df_price, timeperiod = RSI_period)

        #ATRの追加
        df_Yprices['ATR', market_code] = ta.ATR(df_Yprices['High', market_code], df_Yprices['Low', market_code], df_price, timeperiod=ATR_period)
        

    df_technical = df_Yprices.swaplevel(axis=1).sort_index(axis=1, level=0)      #axis=1は列方向のソート、levelで階層指定、inplace=Trueは元オブジェクトを更新
    st.session_state.df_technical = df_technical



    #売買判断条件で銘柄を選定

    #価格フィルタ
    code_price_Filter = []

    #トレンドフィルタ
    code_SMAVlong_Filter = []
    code_perfectOrder_Filter = []
    code_SMAdirection_Filter = []

    #移動平均線シグナル
    code_nearMedianSMA = []
    code_CrossMedianSMA = []
    code_ShortCrossMedianSMA = []

    #バンドタッチシグナル
    code_BBupper_touchSignal = []
    code_BBlower_touchSignal = []
    code_Donchan_touchSignal = []

    #パーフェクトオーダー決定日数
    #※移動平均線が継続した日数
    perfect_order_period = 5       

    #移動平均線の方向決定日数
    #※移動平均線が上向きか下向きか判定するため、移動平均線の前日との大小関係が継続した日数
    sma_direction_period = 5                       


    for market_code in market_codes:
    # --- 価格フィルタ： 単価の上限、下限値設定------------------------------------------------
        priceFilter = df_technical[market_code, 'Close'].iloc[-1] >= Price[0] and\
                            df_technical[market_code, 'Close'].iloc[-1] <= Price[1]
        
        if  priceFilter:
            code_price_Filter.append(market_code)
    # -----------------------------------------------------------------------------------------------------------
        
        
    # --- トレンドフィルタ1： 超長期移動平均線よりも上 -----------------------------------
        trendFilter_01 = df_technical[market_code, 'Close'].iloc[-1] >=  df_technical[market_code, 'SMA'+str(SMA_Vlong)].iloc[-1] 
        
        if  trendFilter_01:
            code_SMAVlong_Filter.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    # --- トレンドフィルタ2： パーフェクトオーダー-------------------------------------------
    #※中期線 > 長期線 > 超長期線
        for i in range(1, perfect_order_period+1):
            trendFilter_02 = True
            
            perfect_inspect = df_technical[market_code, 'SMA'+str(SMA_Long)].iloc[-i] >=  df_technical[market_code, 'SMA'+str(SMA_Vlong)].iloc[-i] and \
                                        df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-i] >=  df_technical[market_code, 'SMA'+str(SMA_Long)].iloc[-i] 
            
            trendFilter_02 = trendFilter_02 and perfect_inspect
            
        if  trendFilter_02:
            code_perfectOrder_Filter.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    # --- トレンドフィルタ3： 移動平均線（中期線）の方向---------------------------------
        for i in range(1, sma_direction_period+1):
            trendFilter_03 = True
            
            direct_inspect = df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-i] >=  df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-(i+1)] 
            
            trendFilter_03 = trendFilter_03 and direct_inspect
            
        if  trendFilter_03:
            code_SMAdirection_Filter.append(market_code)
    # -----------------------------------------------------------------------------------------------------------

            
    # --- 移動平均線シグナル1： 中期移動平均線付近（0.5 × ATR 以内）----------------
        K_delta = 1
        price_delta = K_delta * df_technical[market_code, 'ATR'].iloc[-1]
        smaSignal_01 = df_technical[market_code, 'Close'].iloc[-1] >= (df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-1] - price_delta) and \
                                df_technical[market_code, 'Close'].iloc[-1] <= (df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-1] + price_delta)

        if smaSignal_01:
            code_nearMedianSMA.append(market_code)
    # -----------------------------------------------------------------------------------------------------------
            

    # --- 移動平均線シグナル2： ローソク足と中期移動平均線の交差----------------------
        smaSignal_02 = df_technical[market_code, 'Close'].iloc[-2] <= df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-2]  and \
                                    df_technical[market_code, 'Close'].iloc[-1] >= df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-1]
        
        if smaSignal_02:
            code_CrossMedianSMA.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    # --- 移動平均線シグナル3： 短期と中期移動平均線の交差 -------------------------------
        smaSignal_03 = df_technical[market_code, 'SMA'+str(SMA_Short)].iloc[-2] <= df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-2]  and \
                                df_technical[market_code, 'SMA'+str(SMA_Short)].iloc[-1] >= df_technical[market_code, 'SMA'+str(SMA_Median)].iloc[-1]
        
        if smaSignal_03:
            code_ShortCrossMedianSMA.append(market_code)
    # -----------------------------------------------------------------------------------------------------------



    # --- バンドタッチシグナル4：ボリンジャーバンドのアッパーバンドにタッチ ----
        bandtouchSignal_01 = df_technical[market_code, 'Close'].iloc[-2] <= df_technical[market_code,'BB_upper'].iloc[-2]  and \
                                                df_technical[market_code, 'Close'].iloc[-1] >= df_technical[market_code, 'BB_upper'].iloc[-1]
        
        if bandtouchSignal_01:
            code_BBupper_touchSignal.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    # --- バンドタッチシグナル5：ボリンジャーバンドのロワーバンドにタッチ ----
        bandtouchSignal_02= df_technical[market_code, 'Close'].iloc[-2] >= df_technical[market_code,'BB_lower'].iloc[-2]  and \
                                            df_technical[market_code, 'Close'].iloc[-1] <= df_technical[market_code, 'BB_lower'].iloc[-1]

        if bandtouchSignal_02:
            code_BBlower_touchSignal.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    # --- バンドタッチシグナル6：ドンチャンチャネルにタッチ ---------------------------
        bandtouchSignal_03= df_technical[market_code, 'Close'].iloc[-2] <= df_technical[market_code,'Donchan_high'+str(Donchian_high_period)].iloc[-2]  and \
                                            df_technical[market_code, 'Close'].iloc[-1] >= df_technical[market_code,'Donchan_high'+str(Donchian_high_period)].iloc[-1]
        
        if bandtouchSignal_03:
            code_Donchan_touchSignal.append(market_code)
    # -----------------------------------------------------------------------------------------------------------


    #条件に合致した銘柄のリストを作成（買い判断）
    select_list = code_price_Filter

    #trend Filter
    if SMAVlong_Filter:
        select_list = list(set(select_list)&set(code_SMAVlong_Filter))
        
        if PerfectOrder_Filter:
            select_list = list(set(select_list)&set(code_perfectOrder_Filter))

            if SMAdirection_Filter:
                select_list = list(set(select_list)&set(code_SMAdirection_Filter))
        
    #signal pattern
    if signal == 'Median SMA Cross':
        select_list = list(set(select_list)&set(code_CrossMedianSMA) )
    elif signal == 'Short & MedianSMA Cross':
        select_list = list(set(select_list)&set(code_ShortCrossMedianSMA) )
    elif signal == 'near Median SMA':
        select_list = list(set(select_list)&set(code_nearMedianSMA) )
    elif signal == 'Bollinger Upper Band touch':
        select_list = list(set(select_list)&set(code_BBupper_touchSignal) )
    elif signal == 'Bollinger Lower Band touch':
        select_list = list(set(select_list)&set(code_BBlower_touchSignal) )
    elif signal == 'Donchan Upper channel touch':
        select_list = list(set(select_list)&set(code_Donchan_touchSignal) )

    st.session_state.code_screened = select_list

    return True



def plot_data(symbol):    


    df_code_info = st.session_state.df_JQinfo.set_index('Code')
    df_technical = st.session_state.df_technical

    jq_code = str( int( symbol.replace('.T', '') ) *10 )
    company_name = df_code_info.loc[jq_code, 'CompanyNameEnglish' ]
    
    apds = [mpf.make_addplot(df_technical[symbol, 'BB_upper'], color='w', width=1.5, linestyle='dotted'),
            mpf.make_addplot(df_technical[symbol, 'BB_lower'], color='w', width=1.5, linestyle='dotted'),
            mpf.make_addplot(df_technical[symbol, 'MACDhist'], type='bar', width=1.0, panel=2, alpha=0.5, ylabel='MACD'),
            mpf.make_addplot(df_technical[symbol, 'MACD'], panel=2, color='r', secondary_y=True),
            mpf.make_addplot(df_technical[symbol, 'MACDsignal'], panel=2, color='b', secondary_y=True),
            mpf.make_addplot(df_technical[symbol, 'RSI'], panel=3, type='line', ylabel='RSI')
            ]
    

    df_technical.index = pd.to_datetime(df_technical.index)
    

    fig = mpf.plot( df_technical[symbol],
                    type='candle', style='mike',
                    title=symbol+'  '+company_name,
                    addplot=apds,
                    figsize=(13,10), panel_ratios=(5, 1, 1, 1),
                    datetime_format='%Y/%m/%d',
                    volume=True, volume_panel=1,
                    mav=(SMA_Short, SMA_Median, SMA_Long)
                 )

    st.pyplot(fig)



#===========================================================================================================================================
    




#FrontEnd
#sidebar
st.sidebar.subheader('JQuants API authentication and Get Stocks Data')
st.sidebar.caption('Please enter your e-mail address and password and then press "Get API Data"')
with st.sidebar.form('JQAPI_forms'):
    email_address = st.text_input('email address',User_email)
    password = st.text_input('password', type='password')

    st.session_state.button_Get_API_Data = st.form_submit_button('Get API Data')

    if st.session_state.button_Get_API_Data:
        with st.spinner('Wait for it ...'):
            if get_APIkey(email_address, password): 

                if get_JQstocksPrice():   

                    if get_JQstocksInfo(): 
                        st.success("Success!!")

                    else: st.warning('JQ Stocks info Failure...')

                else: st.warning('JQ Stocks price Failure...')
 
            else:  st.warning('API key Failure...')

        


                    
#main    
st.title('Technical Screener (JP)')

if not any(st.session_state.headers) or\
   st.session_state.df_JQprices.empty or\
   st.session_state.df_JQinfo.empty : 

    st.info('''Plsase authenticate to JQuants to get stocks data in sidebar now.
               You can sign up for JQuant by access to https://jpx-jquants.com/''', icon="ℹ️")
   

st.write('Setting (default params are set )')


#----------------------------------------------------------------------------------
# main>expander
with st.expander('Screening parameter & Technical Signal'):
    tab1, tab2, tab3 = st.tabs(["Terget price and Volume", "Technical Parameter", "Technical signal"])
    
# main>expander>tab
    with tab1:
        Price = st.slider('Price (Yen)',0, 10000, (1000, 3000))
        Min_Volume = st.number_input('minimum Volume ( x10000)', min_value=30, max_value=300, value=50, step=10)

    with tab2:
        col1, col2, col3, col4 = st.columns([1,1,1,1])
        with col1:
            st.write('SMA')
            SMA_Short = st.number_input('Short', min_value=3, max_value=30, value=5, step=1)
            st.write('MACD')
            MACD_Fast_period = st.number_input('fast period', min_value=3, max_value=50, value=12, step=1)
            st.write('Bollinger Band')
            BB_Median_period = st.number_input('median period', min_value=5, max_value=100, value=25, step=1)
            st.write('Donchan Channel')
            Donchian_high_period = st.number_input('high period', min_value=5, max_value=100, value=25, step=1)

        with col2:
            st.write('&nbsp;')
            SMA_Median = st.number_input('Median', min_value=5, max_value=100, value=25, step=1)
            st.write('&nbsp;')
            MACD_Slow_period = st.number_input('slow period', min_value=3, max_value=150, value=26, step=1)
            st.write('&nbsp;')
            BB_sigma = st.number_input('σ :sigma', min_value=1, max_value=3, value=2, step=1)
            st.write('&nbsp;')
            Donchian_low_period = st.number_input('low period', min_value=5, max_value=100, value=25, step=1)

        with col3:
            st.write('&nbsp;')
            SMA_Long = st.number_input('Long', min_value=15, max_value=150, value=75, step=1)
            st.write('&nbsp;')
            MACD_Signal_period = st.number_input('signal period', min_value=3, max_value=100, value=9, step=1)
            st.write('RSI')
            RSI_period = st.number_input('RSI period', min_value=3, max_value=50, value=14, step=1)
            st.write('ATR')
            ATR_period = st.number_input('ATR period', min_value=3, max_value=50, value=14, step=1)


        with col4:
            st.write('&nbsp;')
            SMA_Vlong = st.number_input('very Long period', min_value=50, max_value=500, value=200, step=5)

    with tab3:
        col1, col2 = st.columns([1,1])
        with col1:
            st.write('Trend Filter')
            SMAVlong_Filter = st.checkbox(label="SMA very long Filter", value=True)
            PerfectOrder_Filter = st.checkbox(label="perfect order Filter")
            SMAdirection_Filter = st.checkbox(label="SMA direction Filter",value=True)


        with col2:
            st.write('Band Touch or SMA Cross')
            signal_list = ['Median SMA Cross',
                           'Short & MedianSMA Cross',
                           'near Median SMA',
                           'Bollinger Upper Band  touch',
                           'Bollinger Lower Band touch',
                           'Donchan Upper channel touch',
                           ]
            
            signal = st.radio('select one signal', options=signal_list)




col1, col2 = st.columns([2,1])
with col1:
    screening_day = st.date_input('Day', datetime.date.today())

with col2:
    st.write('&nbsp;')
    st.session_state.button_Screening = st.button("Screening")
    

    if st.session_state.button_Screening:
        with st.spinner('Wait for it ...'):

            if any(st.session_state.headers) and\
               (not st.session_state.df_JQprices.empty) and\
               (not st.session_state.df_JQinfo.empty) : 
                
                if screening_code(): st.success(f"{len(st.session_state.code_screened)} codes Found.")
                else: st.warning('Failure code screening')

                
            else: st.warning('Please get stocks data by sidebar')

st.divider()
#----------------------------------------------------------------------------------

symbol = st.selectbox('Choose stock symbol', options=list(st.session_state.code_screened))



#chart 
if symbol:
    plot_data(symbol)



