# Plots and tables for one version, on an existing cache (run the caching first, e.g. runCachingParallel.sh).
#
# Usage: scripts/runGenericValidation.sh VERSION REVISION [CONFIGDIR]
#   VERSION    passed as --version, i.e. the caching key (V50nano_170pre5, or just V50nano)
#   CONFIGDIR  configs/<CONFIGDIR> to take the plot/table configs from; by default the longest
#              prefix of VERSION (cut at underscores) that is a configs/ dir, e.g. V50nano
VERSION=$1
REVISION=$2
CONFIGDIR=$3
MAX_JOBS=4
RELVAL=false
PERFORMANCE=true
MENU=true

if [[ -z $CONFIGDIR ]]; then
    CONFIGDIR=$VERSION
    while [[ ! -d configs/$CONFIGDIR && $CONFIGDIR == *_* ]]; do
        CONFIGDIR=${CONFIGDIR%_*}
    done
fi
if [[ -z $VERSION || -z $REVISION || ! -d configs/$CONFIGDIR ]]; then
    echo "Usage: scripts/runGenericValidation.sh VERSION REVISION [CONFIGDIR] (no configs/ dir found for '$VERSION')"
    return 1 2>/dev/null || exit 1
fi
if [[ ! -d cache/$VERSION ]]; then
    echo "No cache/$VERSION, run the caching first"
    return 1 2>/dev/null || exit 1
fi
# The plot and table commands are console scripts of the project environment
# (activate it with `micromamba activate ./venv`, or `source setup.sh` for pyenv/).
# Fail before submitting anything if they cannot be run, falling back to the
# known envs: their entry points run with their own venv shebang, so putting the
# bin dir on PATH is equivalent to activating it.
MISSING=""
for CMD in object_performance rate_table rate_plots; do
    command -v $CMD > /dev/null || MISSING="$MISSING $CMD"
done
if [[ -n $MISSING ]]; then
    ENVBIN=""
    for DIR in venv/bin pyenv/bin; do
        if [[ -x $DIR/object_performance && -x $DIR/rate_table && -x $DIR/rate_plots ]]; then
            ENVBIN=$DIR
            break
        fi
    done
    if [[ -z $ENVBIN ]]; then
        echo "Missing:$MISSING - activate the environment first: micromamba activate ./venv (or source setup.sh)"
        return 1 2>/dev/null || exit 1
    fi
    PATH="$PWD/$ENVBIN:$PATH"
    export PATH
    echo "Not on PATH, using $PWD/$ENVBIN for:$MISSING"
fi

echo "Running plots and tables for $VERSION with configs/$CONFIGDIR - Revision = $REVISION"

# Track our own PIDs and check them with `kill -0`. Counting $(jobs -p | wc -l) depends on when
# bash drops finished jobs from its job table, which differs between bash versions: it can let one
# job too many through, or keep counting finished jobs forever (a hang with MAX_JOBS=1).
PIDS=()     # every submitted job, in submission order
NAMES=()    # its log name, parallel to PIDS
RUNNING=()  # the subset possibly still alive, only used to throttle to MAX_JOBS
prune_pids() {
    local alive=() p
    for p in "${RUNNING[@]}"; do kill -0 $p 2>/dev/null && alive+=($p); done
    RUNNING=("${alive[@]}")
}
run_when_ready() {
    prune_pids
    while [ ${#RUNNING[@]} -ge $MAX_JOBS ]; do
        sleep 3
        prune_pids
    done
    # Extract a meaningful identifier from the config path
    local filename=$(basename "$2")  # assumes config is 2nd argument
    local logname=${filename%.*}  # removes file extension
    echo Submitting $logname
    "$@" &> logs/${VERSION}_${REVISION}/${VERSION}_${logname}.log &
    PIDS+=($!)
    RUNNING+=($!)
    NAMES+=($logname)
}
wait_for_jobs() {
    # Wait for every submitted job and report those that failed. A finished job
    # keeps its exit status for `wait <pid>`, so check through the PIDS list: a
    # plain `wait` first would drop them ("not a child of this shell", 127).
    local i rc=0
    RUNNING=()
    for i in "${!PIDS[@]}"; do
        if ! wait ${PIDS[$i]}; then
            echo "FAILED ${NAMES[$i]} (logs/${VERSION}_${REVISION}/${VERSION}_${NAMES[$i]}.log)"
            rc=1
        fi
    done
    PIDS=() NAMES=()
    return $rc
}

mkdir -p logs/${VERSION}_${REVISION}

if [[ $PERFORMANCE == "true" ]]; then
    # === Object Performance (Matching) === #

    # Electrons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/electron_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/electron_matching_eta.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/electron_matching_eta_extended.yaml --version ${VERSION}

    # Photons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/photons_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/photons_matching_eta.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/photons_matching_eta_extended.yaml --version ${VERSION}

    # Jets
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_matching_eta.yaml --version ${VERSION}
    if [[ $RELVAL == "false" ]]; then
	run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_matching_wBTag.yaml --version ${VERSION}
    fi

    # Muons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_matching_eta.yaml --version ${VERSION}

    # TkMuons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tkmuon_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tkmuon_matching_eta.yaml --version ${VERSION}

    if [[ $RELVAL == "false" ]]; then
	# MuonsTF
	run_when_ready object_performance configs/$CONFIGDIR/object_performance/muonTF_matching.yaml --version ${VERSION}
	run_when_ready object_performance configs/$CONFIGDIR/object_performance/muonTF_matching_eta.yaml --version ${VERSION}
    fi

    # Taus
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching_eta.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching_ar.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching_eta_ar.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching_eta_extended.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_matching_highPt.yaml --version ${VERSION}

    # === Object Performance (Triggers/Scalings) === #

    run_when_ready object_performance configs/$CONFIGDIR/object_performance/electron_trigger.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/electron_trigger_extended.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/met_ht_mht.yaml --version ${VERSION} # Sums (all in one!)
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_trigger.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_sc8_trigger.yaml --version ${VERSION} # step 2
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/jets_ext_trigger.yaml --version ${VERSION} # step 2
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_trigger.yaml --version ${VERSION} # includes step 2 disp muons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_trigger_VLoose.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_trigger_Loose.yaml --version ${VERSION} 
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_trigger_Medium.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/muon_trigger_Tight.yaml --version ${VERSION} 
    # run_when_ready object_performance configs/$CONFIGDIR/object_performance/tkmuon_trigger.yaml --version ${VERSION} # commented as it takes a long time
    if [[ $RELVAL == "false" ]]; then
	run_when_ready object_performance configs/$CONFIGDIR/object_performance/muonTF_trigger.yaml --version ${VERSION}
    fi
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_trigger.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_trigger_ar.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/tau_trigger_extended.yaml --version ${VERSION}
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/photons_trigger.yaml --version ${VERSION} # submit later so it's more likely to complete after electrons
    run_when_ready object_performance configs/$CONFIGDIR/object_performance/photons_trigger_extended.yaml --version ${VERSION} # submit later so it's more likely to complete after electrons

    # # === Print Configs (Objects) === #
    # run_when_ready python menu_tools/utils/exportDefs.py -t objects configs/$CONFIGDIR/objects

    echo "Waiting for scalings"
    if ! wait_for_jobs; then
        # Without these jobs the scalings are incomplete, and the menu and rate
        # steps below would silently consume whatever scalings happen to exist.
        echo "Object performance jobs failed, not running the menu and rate steps"
        return 1 2>/dev/null || exit 1
    fi
    echo "Scalings complete"

    source scripts/swapToElectronScalings.sh $VERSION # Explicit scalings swap in case photons finish first
fi

if [[ $MENU == "true" ]]; then
    # === Menu Performance === #

    run_when_ready rate_table configs/$CONFIGDIR/rate_table/step1_cfg.yml --version ${VERSION}
    run_when_ready rate_table configs/$CONFIGDIR/rate_table/step2_cfg.yml --version ${VERSION}
    run_when_ready rate_table configs/$CONFIGDIR/rate_table/step1and2_cfg.yml --version ${VERSION}
    run_when_ready rate_table configs/$CONFIGDIR/rate_table/step1p5_cfg.yml --version ${VERSION}
    run_when_ready rate_table configs/$CONFIGDIR/rate_table/v0p0_cfg.yml --version ${VERSION}

    # # === Print Configs (Menus) === #
    # run_when_ready python menu_tools/utils/exportDefs.py -t triggers configs/$CONFIGDIR/rate_table
fi

if [[ $PERFORMANCE == "true" ]]; then
    # === Object Rates === #

    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/eg.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/muons.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/tkmuons.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/ht.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/met.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/jets.yaml --version ${VERSION} # includes ext jets
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/jets_sc8.yaml --version ${VERSION} # step 2
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/taus.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/bjet.yaml --version ${VERSION}
    run_when_ready rate_plots configs/$CONFIGDIR/rate_plots/disp_muons.yaml --version ${VERSION} # step 2

fi

echo "Plots and tables finished submitting, waiting for them to finish"
# Wait so runSeveralValidation.sh only counts this version as done once its plots are
if ! wait_for_jobs; then
    return 1 2>/dev/null || exit 1
fi
echo "Plots and tables finished!"
