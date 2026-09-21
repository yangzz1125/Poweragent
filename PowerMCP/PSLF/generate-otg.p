/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  STANDARD EPCL PROGRAM SSTOOLS-OUTAGE-NEW FORMAT- VERSION 0002                            ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  EPCL PROGRAM DESCRIPTION                                                                 ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  THIS EPCL PROGRAM IS USED TO:                                                            ***/
/***                                                                                           ***/
/***  CREATE A SIMPLIFIED CONTINGENCY LIST IN NEW FORMAT FOR USE WITH THE SSTOOLS              ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  EPCL PROGRAM UPDATES                                                                     ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/*** CREATED: S.Puchalapalli on 09/16/2016						       ***/
/*** Based on the exisiting "sstools-outage-v5.p" EPCL Program				       ***/
/*** Can create bus, branch, tran, gen, load, shunts, SVD, and breaker type of events          ***/
/***											       ***/				
/***											       ***/
/*** MODIFIED:
/***   VERSION:       DATE:          PROGRAMMER:    CHANGES MADE:                              ***/
/***  --------------- -------------- -------------  -----------------------------------------  ***/
/***	V1		06/13/2017   S.Puchalapalli  Increase the precision of base voltage to ***/
/***						     caputure all the buses  		       ***/	
/***						     Fix the issue with 3-winding transformer  ***/
/***						     definitions 			       ***/
/***			02/27/2018	  S. Mahmood	Divide the contingency list dialog in two to	   ***/
/***							overcome blank panel inconsistency     ***/
/***			08/26/2019	S.Mahmood	Corrected busname writing option       ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  EPCL PROGRAM METHODOLOGY                                                                 ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  STEP 1:  FOLLOW SSTOOLS MANUALS FOR PROCESS                                              ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/
/***                                                                                           ***/
/***  EPCL PROGRAM CODE FOLLOWS:                                                               ***/
/***                                                                                           ***/
/*************************************************************************************************/
/*************************************************************************************************/




/*************************************************************************************************/
/*  First Initialize All Program Variables And Set Default Program Limits                        */
/*************************************************************************************************/

define MAXAREA   5000
define MAXZONE   5000
define MAXSECDD 120000
define MAXTRAN  40000
define MAXGEN   35000
define MAXLOAD  75000
define MAXBUS   100000
define MAXSHUNT 80000
define MAXBRKR  200000


define NAME_LENGTH 12

dim  *des[25][80], *inp[25][8], *title[1][40]
dim  *descr[10][80], *inpu[10]

dim  *file[1][256], *condes[1][80], *longid[1][40], *objStr[1][256]
dim  #mrk[4], #markar[MAXAREA], #arvmin[MAXAREA], #arvmax[MAXAREA]
dim  #markzn[MAXZONE], #znvmin[MAXAREA], #znvmax[MAXAREA]

dim  #pksecdd[MAXSECDD], #pktran[MAXTRAN], #pkgen[MAXGEN], #pkload[MAXLOAD]
dim  #pkbus[MAXBUS], #pkshunt[MAXSHUNT], #pkSVD[MAXSHUNT], #pkbrkr[MAXBRKR]
dim  *redisp[1][80]


/*************************************************************************************************/
/*  EPCL PROGRAM TO BE ADDED AFTER EACH GENERATION OUTAGE (CHANGE THIS EPCL IF DESIRED)          */
/*************************************************************************************************/

*redisp[0] = "redispatch.p"


/*************************************************************************************************/
/*  SEND MESSAGE TO SCREEN THAT THE PROGRAM IS STARTINGING TO GENERATE A CONTINGENCY LIST        */
/*************************************************************************************************/

logterm("<< Running SSTOOLS-OUTAGE to Generate a Contingency List<")


/*************************************************************************************************/
/*  FIRST CHECK TO SEE IF A PSLF HISTORY CASE EXISTS IN MEMORY                                   */
/*    - IF CASE EXISTS IN MEMORY THE USER HAS THE OPTION TO LOAD NEW OR USE EXISTING FILE        */
/*    - IF CASE DOES NOT EXIST IN MEMORY, LOAD CASE                                              */
/*************************************************************************************************/

/*if(casepar[0].nbus < 1)
    @newcase = 0
else
    @newcase = 1
    label newcase
        *title[0] = "Load New/Use Current File"
        *des[0]   = "Load New (0) or Use Current (1) Case In Memory"
        *inp[0]   = "1"
        logbuf(*des[1],"Current Case: ",filepar[0].getf[0])
        *inp[1]   = "Click OK"
        @ret = panel(*title[0],*des[0],*inp[0],2,1)
        if(@ret < 0)
            end
        endif
        @newcase = atof(*inp[0])
endif*/

@newcase = 1

/*if(@newcase = 0)
    logterm("<< Select a PSLF History Case File (*.sav) To Develop A Contingency List From<<")
    @ret = pick("","*.sav","")
    if(@ret < 0)
        end
    endif
    @ret = getf(ret[0].string[0])
    if(@ret < 0)
        logterm("*** ERROR Opening the PSLF History Case File - Terminating EPCL Program<<")
    endif
elseif(@newcase = 1)
    logterm(" Using Current PSLF History Case File In Memory<")
    @ret = savf("temp.wrk")
endif*/

@ret = savf("temp.wrk")

@dupBusNo = 0
@dupBusNm = 0

gosub dupCheck
if( @dupBusNm = 0 )
	@busname = 1                                            /* DEFAULT IS TO USE BUS NAME CONVENTION */
else
	@busname = 0
endif
/*************************************************************************************************/
/*  SECOND ASK USER TO DEFINE CONTINGENCY LIST FILE                                              */
/*    - IF FILE ALREADY EXISTS, CHECK TO SEE IF USER WANTS TO OVERWRITE OR APPEND TO FILE        */
/*    - IF FILE DOES NOT EXIST, CREATE FILE                                                      */
/*************************************************************************************************/

label top
/*logterm("<< Select A Contingency List File To Write Into <<")
@ret = pick("","*.otg","")
if(@ret < 0)
    logterm("*** ERROR Opening the Contingency List File - Terminating EPCL Program<<")
    end
endif*/

*file[0] = "cont.otg"

@ret = openlog(*file[0])



@append = 0
@emsids = 0
@busname = 0




/*************************************************************************************************/
/*  LOOPING THROUGH PEAK SECDD, TRAN AND GEN ARRARYS AND NULLING THEM OUT WITH (-1)              */
/*************************************************************************************************/

for @i = 0  to MAXSECDD-1
    #pksecdd[@i] = -1
next

for @i = 0  to MAXTRAN-1
    #pktran[@i] = -1
next

for @i = 0  to MAXGEN-1
    #pkgen[@i] = -1
next

for @i = 0  to MAXBUS-1
    #pkbus[@i] = -1
next

for @i = 0  to MAXLOAD-1
    #pkload[@i] = -1
next

for @i = 0  to MAXSHUNT-1
    #pkshunt[@i] = -1
next

for @i = 0  to MAXSHUNT-1
    #pkSVD[@i] = -1
next

for @i = 0  to MAXBRKR-1
    #pkbrkr[@i] = -1
next

    

    @eventTime = 1.000000                                   /* DEFAULT TIME FOR CONTINGENCY EVENT   */
@number  = 1                                            /* DEFAULT STARTING CONTINGENCY NUMBER   */
$arzo    = "area"                                       /* DEFAULT IS USING AREA FOR LIST        */
#mrk[0]  = 0                                            /* DEFAULT STARTING AREA/ZONE NUMBER     */
#mrk[1]  = 999                                            /* DEFAULT ENDING   AREA/ZONE NUMBER     */
#mrk[2]  = -1                                           /* DEFAULT STARTING ZONE NUMBER WITHIN AREA RANGE ABOVE  */
#mrk[3]  = -1                                           /* DEFAULT ENDING   ZONE NUMBER WITHIN AREA RANGE ABOVE  */
@vstart  = 100                                          /* DEFAULT LOWER VOLTAGE THRESHOLD       */
@vend    = 999                                          /* DEFAULT UPPER VOLTAGE THRESHOLD       */
@genout  = 1                                            /* DEFAULT IS TO ALLOW GENERATOR OUTAGES */
@busout  = 0                                           /* DEFAULT IS TO NOT ALLOW BUS OUTAGES */
@loadout  = 0                                           /* DEFAULT IS TO NOT ALLOW LOAD OUTAGES */
@shuntout  = 0                                           /* DEFAULT IS TO NOT ALLOW SHUNT OUTAGES */
@SVDout  = 0                                           /* DEFAULT IS TO NOT ALLOW SVD OUTAGES */
@brkrout  = 0                                           /* DEFAULT IS TO NOT ALLOW BREAKER OUTAGES */
@stckbrkr  = 0                                           /* DEFAULT IS TO NOT ALLOW STUCK BREAKER EVENTS */
@redepcl = 0											/* DEFAULT IS SET TO NOT INCLUDE REDISPATCH EPCL */
@smin    = 100.0                                        /* DEFAULT IS 100 MVABASE MINIMUM        */

@lineRfact = 1.0                                        /* Default ranking factor for Line outages    */
@tranRfact = 1.0                                        /* Default ranking factor for Transformer outages    */
@genRfact  = 1.0                                        /* Default ranking factor for Generator outages    */
@otherRfact  = 1.0                                      /* Default ranking factor for all other outages    */
@skip	   =   0					/* Default do no skip any contingency    */
	
	
    if(#mrk[0] < 0)
        logterm("*** ERROR: Range of Areas - Illegally Entered - Try Again!!!<")
    endif

    if(#mrk[1] = 0)
        #mrk[1] = #mrk[0]
    endif

    if(#mrk[3] = 0 or #mrk[3]<0)
        #mrk[3] = #mrk[2]
    endif

    if(#mrk[2] >=0 and #mrk[3] >=0 and $arzo = "area")
    	@zfilter = 1
    endif

/*************************************************************************************************/
/*  START SELECTION OF ELEMENTS: TAG ELEMENTS AND WILL WRITE OUT THE RECORDS UPON EXITING EPCL   */
/*************************************************************************************************/

    if(@zfilter = 1)
    	logprint(*file[0],"# Contingency Selection Criteria: From ",$arzo, " ",#mrk[0]," to ",#mrk[1],"; ","zone", " ",#mrk[2]," to ",#mrk[3],"; ",@vstart," kV to ", @vend," kV <")
    else
    	logprint(*file[0],"# Contingency Selection Criteria: From ",$arzo, " ",#mrk[0]," to ",#mrk[1],"; ",@vstart," kV to ", @vend," kV <")
    endif

    /*********************************************************************************************/
    /*  LOOP THROUGH SECDD (TRANSMISSION LINE IMPEDANCE) EDIT TABLE                              */
    /*    - THREE CONDITIONS MUST BE MET IN ORDER TO ADD LINE INTO CONTINGENCY LIST              */
    /*      1. THE ELEMENT, THE FROM BUS, OR THE TO BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET */
    /*      2. THE FROM BUS VOLTAGE MUST FALL WITHIN THE VOLTAGE RANGE SET                       */
    /*      3. THE LINE IMPEDANCE MUST BE GREATER THAN THE JUMPER IMPEDANCE THRESHOLD            */
    /*********************************************************************************************/

    for @i = 0 to casepar[0].nbrsec-1

        if(#pksecdd[@i] > 0)     /* DESIGNATES THAT LINE HAS ALREADY BEEN PICKED FOR CONTINGENCY */
            continue
        endif

        @from = secdd[@i].ifrom
        @to   = secdd[@i].ito

        if($arzo = "area")
            @tt = secdd[@i].area
            @t1 = busd[@from].area
            @t2 = busd[@to].area
        else
            @tt = secdd[@i].zone
            @t1 = busd[@from].zone
            @t2 = busd[@to].zone
        endif

	if(@zfilter = 1)
            @z1 = secdd[@i].zone
            @z2 = busd[@from].zone
            @z3 = busd[@to].zone
	endif

        @opt1 = 0
        @opt2 = 0
        @opt3 = 0
        @temp1 = 0
        @temp2 = 0
        @temp3 = 0


        if(@tt >= #mrk[0] and @tt <= #mrk[1])
            @opt1 = 1
            @temp1 = 1
        endif
        if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
            @opt1 = 1
            @temp2 = 1
        endif
        if(@t2 >= #mrk[0] and @t2 <= #mrk[1])
            @opt1 = 1
            @temp3 = 1
        endif

        if((busd[@from].basekv >= @vstart) and (busd[@from].basekv <= @vend))
            @opt2 = 1
        endif

        if(abs(secdd[@i].zsecx) > solpar[0].zeps)
            @opt3 = 1
        endif

	if(@zfilter = 1)
	    if(@temp1)
		    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
			@opt1 = 1
		    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
			@opt1 = 1
		    elseif(@temp3 and @z3 >= #mrk[2] and @z3 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    elseif(@temp2)
		    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    elseif(@temp3)
		    if(@z3 >= #mrk[2] and @z3 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    endif

	endif

        if(@opt1 and @opt2 and @opt3)
            #pksecdd[@i] = 1
        endif

    next


    /*********************************************************************************************/
    /*  LOOP THROUGH TRAN (TRANSFORMER) EDIT TABLE                                               */
    /*    - TWO CONDITIONS MUST BE MET IN ORDER TO ADD TRANSFORMER INTO CONTINGENCY LIST         */
    /*      1. THE ELEMENT, THE FROM BUS, OR THE TO BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET */
    /*      2. BOTH THE FROM AND TO BUS VOLTAGES MUST FALL WITHIN THE VOLTAGE RANGE SET          */
    /*********************************************************************************************/

    for @i = 0 to casepar[0].ntran-1

        if(#pktran[@i] > 0)      /* DESIGNATES THAT XFMR HAS ALREADY BEEN PICKED FOR CONTINGENCY */
            continue
        endif

        @from = tran[@i].ifrom
        @to   = tran[@i].ito

        if($arzo = "area")
            @tt = tran[@i].area
            @t1 = busd[@from].area
            @t2 = busd[@to].area
        else
            @tt = tran[@i].zone
            @t1 = busd[@from].zone
            @t2 = busd[@to].zone
        endif

        if(@zfilter = 1)
	    @z1 = tran[@i].zone
	    @z2 = busd[@from].zone
	    @z3 = busd[@to].zone
	endif

        @opt1 = 0
        @opt2 = 0
        @temp1 = 0
        @temp2 = 0
        @temp3 = 0

        if(@tt >= #mrk[0] and @tt <= #mrk[1])
            @opt1 = 1
            @temp1 = 1
        endif
        if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
            @opt1 = 1
            @temp2 = 1
        endif
        if(@t2 >= #mrk[0] and @t2 <= #mrk[1])
            @opt1 = 1
            @temp3 = 1
        endif

        if((busd[@from].basekv >= @vstart) and (busd[@from].basekv <= @vend))
            if((busd[@to].basekv >= @vstart) and (busd[@to].basekv <= @vend))
                @opt2 = 1
            endif
        endif

	if(@zfilter = 1)
	    if(@temp1)
		    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
			@opt1 = 1
		    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
			@opt1 = 1
		    elseif(@temp3 and @z3 >= #mrk[2] and @z3 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    elseif(@temp2)
		    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    elseif(@temp3)
		    if(@z3 >= #mrk[2] and @z3 <= #mrk[3])
			@opt1 = 1
		    else
			@opt1 = 0
		    endif
	    endif

	endif

        if(@opt1 and @opt2)
            #pktran[@i] = 1
        endif

    next


    /*********************************************************************************************/
    /*  LOOP THROUGH GENS (GENERATOR) EDIT TABLE                                                 */
    /*    - THREE CONDITIONS MUST BE MET IN ORDER TO ADD GENERATOR INTO CONTINGENCY LIST         */
    /*      1. THE USER WANTS TO INCLUDE GENERATOR OUTAGES                                       */
    /*      2. THE ELEMENT OR THE FROM BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET              */
    /*      3. THE GENERATOR MVABASE MUST BE LARGER THAN THE MINIMUM MVABASE TO TRIP             */
    /*********************************************************************************************/

    if(@genout)

        for @i = 0 to casepar[0].ngen-1

            if(#pkgen[@i] > 0)   /* DESIGNATES THAT GEN HAS ALREADY BEEN PICKED FOR CONTINGENCY  */
                continue
            endif

            @ibs = gens[@i].ibgen

            if($arzo = "area")
                @tt = gens[@i].area
                @t1 = busd[@ibs].area
            else
                @tt = gens[@i].zone
                @t1 = busd[@ibs].zone
            endif

	    if(@zfilter = 1)
	 	@z1 = gens[@i].zone
	 	@z2 = busd[@ibs].zone
	    endif

            @opt1 = 0
            @opt2 = 0
      	    @temp1 = 0
            @temp2 = 0

            if(@tt >= #mrk[0] and @tt <= #mrk[1])
                @opt1 = 1
                @temp1 = 1
            endif
            if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
                @opt1 = 1
                @temp2 = 1
            endif

            if(gens[@i].mbase >= @smin)
                @opt2 = 1
            endif

	    if(@zfilter = 1)
		    if(@temp1)
			    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
				@opt1 = 1
			    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    elseif(@temp2)
			    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    endif
	    endif

            if(@opt1 and @opt2)
                #pkgen[@i] = 1
            endif

        next

    endif


    /*********************************************************************************************/
    /*  LOOP THROUGH BUS EDIT TABLE                                                 		 */
    /*    - TWO CONDITIONS MUST BE MET IN ORDER TO ADD BUS INTO CONTINGENCY LIST         	 */
    /*      1. THE USER WANTS TO INCLUDE BUS OUTAGES                                       	 */
    /*      2. THE BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET              			 */
    /*********************************************************************************************/

    if(@busout)

        for @i = 0 to casepar[0].nbus-1

            if(#pkbus[@i] > 0)   /* DESIGNATES THAT BUS HAS ALREADY BEEN PICKED FOR CONTINGENCY  */
                continue
            endif

            if($arzo = "area")
                @t1 = busd[@i].area
            else
                @t1 = busd[@i].zone
            endif

	    if(@zfilter = 1)
	 	@z1 = busd[@i].zone
	    endif

            @opt1 = 0
            @opt2 = 0
      	    @temp1 = 0
            @temp2 = 0

            if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
                @opt1 = 1
                @temp1 = 1
            endif


	    if(@zfilter = 1)
		    if(@temp1)
			    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    endif
	    endif

            if(@opt1)
                #pkbus[@i] = 1
            endif

        next

    endif


    /*********************************************************************************************/
    /*  LOOP THROUGH LOAD EDIT TABLE                                                 		 */
    /*    - TWO CONDITIONS MUST BE MET IN ORDER TO ADD LOAD INTO CONTINGENCY LIST         	 */
    /*      1. THE USER WANTS TO INCLUDE LOAD OUTAGES                                       	 */
    /*      2. THE ELEMENT OR THE FROM BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET              */
    /*********************************************************************************************/

    if(@loadout)

        for @i = 0 to casepar[0].nload-1

            if(#pkload[@i] > 0)   /* DESIGNATES THAT LOAD HAS ALREADY BEEN PICKED FOR CONTINGENCY  */
                continue
            endif

            @lbs = load[@i].lbus

            if($arzo = "area")
                @tt = load[@i].area
                @t1 = busd[@lbs].area
            else
                @tt = load[@i].zone
                @t1 = busd[@lbs].zone
            endif

	    if(@zfilter = 1)
	 	@z1 = load[@i].zone
	 	@z2 = busd[@lbs].zone)
	    endif

            @opt1 = 0
            @opt2 = 0
      	    @temp1 = 0
            @temp2 = 0

            if(@tt >= #mrk[0] and @tt <= #mrk[1])
                @opt1 = 1
                @temp1 = 1
            endif
            if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
                @opt1 = 1
                @temp2 = 1
            endif


	    if(@zfilter = 1)
		    if(@temp1)
			    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
				@opt1 = 1
			    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    elseif(@temp2)
			    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    endif
	    endif

            if(@opt1)
                #pkload[@i] = 1
            endif

        next

    endif


    /*********************************************************************************************/
    /*  LOOP THROUGH SHUNT EDIT TABLE (INCLUDES BOTH BUS AND LINE CONNECTED                      */
    /*    - TWO CONDITIONS MUST BE MET IN ORDER TO ADD SHUNT INTO CONTINGENCY LIST               */
    /*      1. THE ELEMENT, THE FROM BUS, OR THE TO BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET */
    /*      2. THE ELEMENT OR THE FROM BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET              */
    /*********************************************************************************************/

    if(@shuntout)
	    for @i = 0 to casepar[0].nshunt-1

		if(#pkshunt[@i] > 0)     /* DESIGNATES THAT SHUNT HAS ALREADY BEEN PICKED FOR CONTINGENCY */
		    continue
		endif

		@from = shunt[@i].ifrom
		@to   = shunt[@i].ito

		if($arzo = "area")
		    @tt = shunt[@i].area
		    @t1 = busd[@from].area
		    if(@to >= 0)
		    	@t2 = busd[@to].area
		    endif
		else
		    @tt = shunt[@i].zone
		    @t1 = busd[@from].zone
		    if(@to >= 0)
		    	@t2 = busd[@to].zone
		    endif
		endif

		if(@zfilter = 1)
		    @z1 = shunt[@i].zone
		    @z2 = busd[@from].zone
		    if(@to >= 0)
		    	@z3 = busd[@to].zone
		    endif
		endif

		@opt1 = 0
		@opt2 = 0
		@opt3 = 0
		@temp1 = 0
		@temp2 = 0
		@temp3 = 0


		if(@tt >= #mrk[0] and @tt <= #mrk[1])
		    @opt1 = 1
		    @temp1 = 1
		endif
		if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
		    @opt1 = 1
		    @temp2 = 1
		endif
		if(@to >= 0)
			if(@t2 >= #mrk[0] and @t2 <= #mrk[1])
			    @opt1 = 1
			    @temp3 = 1
			endif
		endif

		if(@zfilter = 1)
		    if(@temp1)
			    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
				@opt1 = 1
			    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    elseif(@temp3 and @z3 >= #mrk[2] and @z3 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    elseif(@temp2)
			    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    elseif(@temp3)
			    if(@z3 >= #mrk[2] and @z3 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    endif

		endif

		if(@opt1)
		    #pkshunt[@i] = 1
		endif

	    next
    endif
    


    /*********************************************************************************************/
    /*  LOOP THROUGH SVD EDIT TABLE                                                 		 */
    /*    - TWO CONDITIONS MUST BE MET IN ORDER TO ADD SVD INTO CONTINGENCY LIST         	 */
    /*      1. THE USER WANTS TO INCLUDE SVD OUTAGES                                       	 */
    /*      2. THE ELEMENT OR THE FROM BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET              */
    /*********************************************************************************************/

    if(@SVDout)

        for @i = 0 to casepar[0].nsvd-1

            if(#pkSVD[@i] > 0)   /* DESIGNATES THAT SVD HAS ALREADY BEEN PICKED FOR CONTINGENCY  */
                continue
            endif

            @ibs = svd[@i].ibus

            if($arzo = "area")
                @tt = svd[@i].area
                @t1 = busd[@ibs].area
            else
                @tt = svd[@i].zone
                @t1 = busd[@ibs].zone
            endif

	    if(@zfilter = 1)
	 	@z1 = svd[@i].zone
	 	@z2 = busd[@ibs].zone)
	    endif

            @opt1 = 0
            @opt2 = 0
      	    @temp1 = 0
            @temp2 = 0

            if(@tt >= #mrk[0] and @tt <= #mrk[1])
                @opt1 = 1
                @temp1 = 1
            endif
            if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
                @opt1 = 1
                @temp2 = 1
            endif


	    if(@zfilter = 1)
		    if(@temp1)
			    if(@z1 >= #mrk[2] and @z1 <= #mrk[3])
				@opt1 = 1
			    elseif(@temp2 and @z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    elseif(@temp2)
			    if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
				@opt1 = 1
			    else
				@opt1 = 0
			    endif
		    endif
	    endif

            if(@opt1)
                #pkSVD[@i] = 1
            endif

        next

    endif


    /*********************************************************************************************/
    /*  LOOP THROUGH BREAKER EDIT TABLE                                                 		 */
    /*    - THREE CONDITIONS MUST BE MET IN ORDER TO ADD BREAKER INTO CONTINGENCY LIST         	 */
    /*      1. THE USER WANTS TO INCLUDE BREAKER OUTAGES                                       	 */
    /*      2. THE ELEMENT, THE FROM BUS, OR THE TO BUS MUST FALL WITHIN THE AREA/ZONE RANGE SET */
    /*      3. THE FROM BUS VOLTAGE MUST FALL WITHIN THE VOLTAGE RANGE SET                       */
    /*********************************************************************************************/

    if(@brkrout)

        for @i = 0 to casepar[0].nbreaker-1

            if(#pkbrkr[@i] > 0)   /* DESIGNATES THAT BREAKER HAS ALREADY BEEN PICKED FOR CONTINGENCY  */
                continue
            endif

            @from = brkr[@i].ifrom
            @to   = brkr[@i].ito

            if($arzo = "area")
		@t1 = busd[@from].area
		@t2 = busd[@to].area
	    else
		@t1 = busd[@from].zone
		@t2 = busd[@to].zone
	    endif
	    
	    if(@zfilter = 1)
	       @z2 = busd[@from].zone
	       @z3 = busd[@to].zone
	    endif
	    
	    @opt1 = 0
	    @opt2 = 0
	    
	    @temp2 = 0
	    @temp3 = 0

            /* include tie */
	    if(@t1 >= #mrk[0] and @t1 <= #mrk[1])
	       @opt1 = 1
	       @temp2 = 1
	    endif
	    if(@t2 >= #mrk[0] and @t2 <= #mrk[1])
	       @opt1 = 1
	       @temp3 = 1
	    endif
	    
	    if((busd[@from].basekv >= @vstart) and (busd[@from].basekv <= @vend))
	       @opt2 = 1
            endif


	    if(@zfilter = 1)	            
	       if(@temp2)
		  if(@z2 >= #mrk[2] and @z2 <= #mrk[3])
		     @opt1 = 1
		  else
		     @opt1 = 0
		  endif
	       elseif(@temp3)
		  if(@z3 >= #mrk[2] and @z3 <= #mrk[3])
		     @opt1 = 1
		  else
		     @opt1 = 0
		  endif
	       endif	    
            endif

            if(@opt1 and @opt2)
                #pkbrkr[@i] = 1
            endif

        next

    endif

    
    /*********************************************************************************************/
    /*  RETURN VALUE FROM THE PANEL CALL ABOVE, IF < 0, QUIT FOR LOOP                            */
    /*********************************************************************************************

    if(@pan-ret < 0 or @pan-ret1 < 0)
        quitfor
    endif


*************************************************************************************************/
/*  END SELECTION OF ELEMENTS LOOP                                                               */
/*************************************************************************************************/




/*************************************************************************************************/
/*  ALL ELEMENTS ARE TAGGED FROM SELECTION LOOP, WRITE OUT THE CONTINGENCY LIST FILE (*.OTG)     */
/*    - CHECK TO DETERMINE IF FILE IS BEING OVERWRITTEN OR APPENDED TO                           */
/*************************************************************************************************/

@nnew = 0


/*************************************************************************************************/
/*  LOOP THROUGH SECDD TABLE                                                                     */
/*************************************************************************************************/

for @i = 0 to casepar[0].nbrsec-1

    if(#pksecdd[@i] < 0)
        continue
    endif

    @from = secdd[@i].ifrom
    @to   = secdd[@i].ito
    $ck   = secdd[@i].ck
    @nsec = secdd[@i].nsec


    /*********************************************************************************************/
    /*  CHECK FOR MULTI-SECTION LINES, DO NOT ENTER MORE THAN ONE TIME                           */
    /*********************************************************************************************/

    if(@i > 0)
        if(#pksecdd[@i-1] > 0)
            if((@from = secdd[@i-1].ifrom) and (@to = secdd[@i-1].ito) and ($ck = secdd[@i-1].ck))
                continue
            endif
        endif
    endif


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                        "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((secdd[@i].lid = *longid[0]) or (secdd[@i].lid = $space) or (secdd[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "line_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Line ID = ",secdd[@i].lid)
    else
    	logbuf(*condes[0],"Line ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:5:1," to ",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:5:1," Circuit ",$ck)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@lineRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/

    if(@useems)
        logprint(*file[0]," ^secdd  '",secdd[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^secdd '",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",$ck:2:0,"' ",@nsec:2:0,"^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^secdd  ",busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"   '",$ck:2:0,"' ",@nsec:2:0,"^    ^open^     ",@eventTime:7:6 ,"<")
	    endif
    endif

    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH TRAN TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].ntran-1

    if(#pktran[@i] < 0)
        continue
    endif

    @from = tran[@i].ifrom
    @to   = tran[@i].ito
    $ck   = tran[@i].ck

    @itert = tran[@i].itert
    if( @itert >= 0 )
        $tertname = busd[@itert].busnam:NAME_LENGTH:0
        @tertkv   = busd[@itert].basekv
        @tert = busd[@itert].extnum
    else
        $tertname = "            "
        @tertkv   = 0.0
        @tert = -1
    endif

    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/

    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((tran[@i].lid = *longid[0]) or (tran[@i].lid = $space) or (tran[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "tran_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Tran ID = ",tran[@i].lid)
    else
    	logbuf(*condes[0],"Tran ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:2," to ",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:2," Circuit ",$ck," ",$tertname:NAME_LENGTH:0," ",@tertkv:6:2)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@tranRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^tran  '",tran[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
	    	if(@itert >= 0)
	    		logbuf(*objStr[0], "'",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",busd[@itert].busnam:NAME_LENGTH:0," ",busd[@itert].basekv:6:5,"'  '",$ck:2:0,"'")
		else
			logbuf(*objStr[0], "'",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",$ck:2:0,"'")			
		endif		
	    else
	    	if(@itert >= 0)
	    		logbuf(*objStr[0], busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"  ",busd[@itert].extnum:8:0,"   '",$ck:2:0,"'")
		else
			logbuf(*objStr[0], busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"   '",$ck:2:0,"'")
		endif
	    endif
	    logprint(*file[0]," ^tran  ",*objStr[0],"^    ^open^     ",@eventTime:7:6 ,"<")
    endif

    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH GENS TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].ngen-1

    if(#pkgen[@i] < 0)
        continue
    endif

    @bus = gens[@i].ibgen
    $id  = gens[@i].id


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((gens[@i].lid = *longid[0]) or (gens[@i].lid = $space) or (gens[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "gen_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Gen ID = ",gens[@i].lid)
    else
    	logbuf(*condes[0],"Gen  ",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:5:1," Unit ID ",$id)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@genRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^gen  '",gens[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^gen '",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:6:5,"'  '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^gen  ",busd[@bus].extnum:8:0,"   '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    endif
    endif


    /*********************************************************************************************/
    /*  REDISPATCHING EPCL DEFINED EARLY IN THIS EPCL ALSO PRINTED OUT IN CONTINGENCY LIST       */
    /*********************************************************************************************/
	if( @redepcl )
    	logprint(*file[0]," epcl ^", *redisp[0],"^ <")
	endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH BUS TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].nbus-1

    if(#pkbus[@i] < 0)
        continue
    endif

    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((busd[@i].lid = *longid[0]) or (busd[@i].lid = $space) or (busd[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "bus_" + $txt
    if(@useems)
    	logbuf(*condes[0],"BUS ID = ",busd[@i].lid)
    else
    	logbuf(*condes[0],"Bus  ",busd[@i].busnam:NAME_LENGTH:0," ",busd[@i].basekv:5:1)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@otherRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^bus  '",busd[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^bus '",busd[@i].busnam:NAME_LENGTH:0," ",busd[@i].basekv:6:5,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^bus  ",busd[@i].extnum:8:0,"^    ^open^     ",@eventTime:7:6 ,"<")
	    endif
    endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH LOAD TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].nload-1

    if(#pkload[@i] < 0)
        continue
    endif

    @bus = load[@i].lbus
    $id  = load[@i].id


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((load[@i].lid = *longid[0]) or (load[@i].lid = $space) or (load[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "load_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Load ID = ",load[@i].lid)
    else
    	logbuf(*condes[0],"Load  ",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:5:1," ID ",$id)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@otherRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^load  '",load[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^load '",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:6:5,"'  '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^load  ",busd[@bus].extnum:8:0,"   '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    endif
    endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH SHUNT TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].nshunt-1

    if(#pkshunt[@i] < 0)
        continue
    endif

    @from = shunt[@i].ifrom
    @to   = shunt[@i].ito
    $id   = shunt[@i].id
    $ck   = shunt[@i].ck
    @nsec = shunt[@i].nsecsh


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                        "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((shunt[@i].lid = *longid[0]) or (shunt[@i].lid = $space) or (shunt[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "shunt_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Shunt ID = ",shunt[@i].lid)
    else
    	if(@to >= 0)
    		logbuf(*condes[0],"Line Shunt ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:5:1," to ",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:5:1," ID ",$id)
    	else
    		logbuf(*condes[0],"Bus Shunt ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:5:1," ID ",$id)
    	endif
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@otherRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/

    if(@useems)
        logprint(*file[0]," ^shunt  '",shunt[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
	    	if(@to >= 0)
			logbuf(*objStr[0], "'",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",$ck:2:0,"'  '",$id:2:0,"'  ",@nsec:2:0)
		else
			logbuf(*objStr[0], "'",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",$id:2:0,"'")
		endif
	    else
	    	if(@to >= 0)			
			logbuf(*objStr[0], busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"  '",$ck:2:0,"'  '",$id:2:0,"'  ",@nsec:2:0)
		else
			logbuf(*objStr[0], busd[@from].extnum:8:0,"  '",$id:2:0,"'")
		endif
	    endif
	    logprint(*file[0]," ^shunt  ",*objStr[0],"^    ^open^     ",@eventTime:7:6 ,"<")
    endif

    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH SVD TABLE                                                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].nsvd-1

    if(#pkSVD[@i] < 0)
        continue
    endif

    @bus = svd[@i].ibus
    $id  = svd[@i].id


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((svd[@i].lid = *longid[0]) or (svd[@i].lid = $space) or (svd[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "svd_" + $txt
    if(@useems)
    	logbuf(*condes[0],"SVD ID = ",svd[@i].lid)
    else
    	logbuf(*condes[0],"SVD  ",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:5:1," ID ",$id)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@otherRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^svd  '",svd[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^svd '",busd[@bus].busnam:NAME_LENGTH:0," ",busd[@bus].basekv:6:5,"'  '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^svd  ",busd[@bus].extnum:8:0,"   '",$id:2:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    endif
    endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next


/*************************************************************************************************/
/*  LOOP THROUGH BREAKER TABLE                                                                   */
/*************************************************************************************************/

for @i = 0 to casepar[0].nbreaker-1

    if(#pkbrkr[@i] < 0)
        continue
    endif

    @from = brkr[@i].ifrom
    @to   = brkr[@i].ito
    $ck   = brkr[@i].id


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((brkr[@i].lid = *longid[0]) or (brkr[@i].lid = $space) or (brkr[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "brkr_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Breaker ID = ",brkr[@i].lid)
    else
    	logbuf(*condes[0],"brkr ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:5:1," to ",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:5:1," Circuit ",$ck)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@lineRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^breaker  '",brkr[@i].lid,"'^    ^open^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^breaker '",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",$ck:8:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^breaker  ",busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"   '",$ck:8:0,"'","^    ^open^     ",@eventTime:7:6 ,"<")
	    endif

    endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1

next

if(@stckbrkr)
/*************************************************************************************************/
/*  LOOP THROUGH BREAKER TABLE FOR STUCK BREAKER EVENT TYPE                                      */
/*************************************************************************************************/

for @i = 0 to casepar[0].nbreaker-1

    if(#pkbrkr[@i] < 0)
        continue
    endif

    @from = brkr[@i].ifrom
    @to   = brkr[@i].ito
    $ck   = brkr[@i].id


    /*********************************************************************************************/
    /*  CONTINGENCY LABEL AND CONTINGENCY DESCRIPTION DEFINED AND PRINTED OUT                    */
    /*********************************************************************************************/
    *longid[0] = "                                "
    $space = " "
    $blank = ""
    if(@emsids)
    	@useems = 1
    	if((brkr[@i].lid = *longid[0]) or (brkr[@i].lid = $space) or (brkr[@i].lid = $blank))
    		@useems = 0
    	endif
    endif

    logbuf($txt,@number)
    $connam = "stckbrkr_" + $txt
    if(@useems)
    	logbuf(*condes[0],"Breaker ID = ",brkr[@i].lid)
    else
    	logbuf(*condes[0],"brkr ",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:5:1," to ",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:5:1," Circuit ",$ck)
    endif
    logprint(*file[0],"^",$connam,"^    ^",*condes[0],"^   ",@lineRfact:6:2,"  ^^", "    ^^","    ^^","    ", @skip,"<")


    /*********************************************************************************************/
    /*  CONTINGENCY OUTAGE PRINTED OUT BASED ON BUS NAME+kV OR BUS NUMBER                        */
    /*********************************************************************************************/
    if(@useems)
            logprint(*file[0]," ^breaker  '",brkr[@i].lid,"'^    ^stuck^     ",@eventTime:7:6 ,"<")
    else
	    if(@busname)
		logprint(*file[0]," ^breaker '",busd[@from].busnam:NAME_LENGTH:0," ",busd[@from].basekv:6:5,"'  '",busd[@to].busnam:NAME_LENGTH:0," ",busd[@to].basekv:6:5,"'  '",$ck:8:0,"'","^    ^stuck^     ",@eventTime:7:6 ,"<")
	    else
		logprint(*file[0]," ^breaker  ",busd[@from].extnum:8:0,"  ",busd[@to].extnum:8:0,"   '",$ck:8:0,"'","^    ^stuck^     ",@eventTime:7:6 ,"<")
	    endif

    endif
    logprint(*file[0],"0<")


    /*********************************************************************************************/
    /*  COUNTERS                                                                                 */
    /*********************************************************************************************/

    @number = @number + 1
    @nnew   = @nnew + 1
next
endif
/*************************************************************************************************/
/*  FINISH CONTINGENCY LIST FILE                                                                 */
/*************************************************************************************************/

logprint(*file[0],"end<# End of Contingency List, ",@nnew," Contingencies Added to List<")

@zz = close(*file[0])

logterm(" The Automated Contingency EPCL Program Created ",@nnew," New Contingencies<")
end


subroutine dupCheck

	$file = "duplicate.txt"
	@ret = openlog( $file )
	if( @ret < 0 )
		logterm("Cannot open file ",$file,"<")
	endif
	@dupBusNo = 0
	@dupBusNm = 0

	logterm("<<<")
	@ret = sort("busd.","01","ff")
	@dupBusNo = 0
	for @i = 1 to casepar[0].nbusd-1
		if( busd[@i].extnum = busd[@i-1].extnum )
				logprint( $file,"busd  table same bus number    at ",busident(@i,0, 7, 12, 7.3),"<")
				@dupBusNo = 1
		endif
	next
	if( @dupBusNo = 1 )
		@ret = beep()
		logterm("<<****Duplicate bus numbers found<")
		logterm("Using [Bus Name + kv] as bus identifier to create contingencies****<")
		logterm("Duplicate bus info written to file ",$file,"<")
	endif

	logterm("<<<")
	@ret = sort("busd","0012","ffff") /* sort names then basekv */
	@dupBusNm = 0
	for @i = 1 to casepar[0].nbus-1
		if( busd[@i].busnam = busd[@i-1].busnam )
			if ( busd[@i].basekv=busd[@i-1].basekv)
				logprint( $file,"busd  table same bus name      at ",busident(@i,0, 7, 12, 7.3)," and ",busident(@i-1,0, 7, 12, 7.3),"<")
				@dupBusNm = 1
			endif
		endif
	next
	if( @dupBusNm = 1 )
		@ret = beep()
		logterm("<<****Duplicate bus names found<")
		logterm("Using [Bus Number] as bus identifier to create contingencies****<")
		logterm("Duplicate bus info written to file ",$file,"<")
	endif

	if( (@dupBusNm = 1) and (@dupBusNo = 1) )
		logterm("<<******Duplicate [bus numbers] as well as [busnames and voltage] found in the case<")
		logterm("Please get rid of duplications or it would cause inaccuries in results<")
		logterm("Terminating EPCL<*******<<")
		@ret = beep()
		end
	endif

	@ret = close( $file )

	logterm("<<")
	@ret = getf( filepar[0].getf )

return
