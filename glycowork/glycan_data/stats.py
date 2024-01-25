import pandas as pd
import numpy as np
import math
import warnings
from collections import defaultdict
from sklearn.ensemble import RandomForestRegressor
from sklearn.base import BaseEstimator
from scipy.special import gammaln
from scipy.stats import wilcoxon, rankdata, norm, chi2, t
import scipy.integrate as integrate
from statsmodels.stats.multitest import multipletests
from statsmodels.tools.sm_exceptions import ConvergenceWarning
import statsmodels.api as sm
import statsmodels.formula.api as smf
rng = np.random.default_rng(42)


def fast_two_sum(a, b):
  """Assume abs(a) >= abs(b)"""
  x = int(a) + int(b)
  y = b - (x - int(a))
  return [x] if y == 0 else [x, y]


def two_sum(a, b):
  """For unknown order of a and b"""
  x = int(a) + int(b)
  y = (a - (x - int(b))) + (b - (x - int(a)))
  return [x] if y == 0 else [x, y]


def expansion_sum(*args):
  """For the expansion sum of floating points"""
  g = sorted(args, reverse = True)
  q, *h = fast_two_sum(np.array(g[0]), np.array(g[1]))
  for val in g[2:]:
    z = two_sum(q, np.array(val))
    q, *extra = z
    if extra:
      h += extra
  return [h, q] if h else q


def hlm(z):
  """Hodges-Lehmann estimator of the median"""
  z = np.array(z)
  zz = np.add.outer(z, z)
  zz = zz[np.tril_indices(len(z))]
  return np.median(zz) / 2


def update_cf_for_m_n(m, n, MM, cf):
  """Constructs cumulative frequency table for experimental parameters defined in the function 'jtkinit'"""
  P = min(m + n, MM)
  for t in range(n + 1, P + 1):  # Zero-based offset t
    for u in range(MM, t - 1, -1):  # One-based descending index u
      cf[u] = expansion_sum(cf[u], -cf[u - t])  # Shewchuk algorithm
  Q = min(m, MM)
  for s in range(1, Q + 1): # Zero-based offset s
    for u in range(s, MM + 1):  # One-based descending index u
      cf[u] = expansion_sum(cf[u], cf[u - s])  # Shewchuk algorithm


def cohen_d(x, y, paired = False):
  """calculates effect size between two groups\n
  | Arguments:
  | :-
  | x (list or 1D-array): comparison group containing numerical data
  | y (list or 1D-array): comparison group containing numerical data
  | paired (bool): whether samples are paired or not (e.g., tumor & tumor-adjacent tissue from same patient); default:False\n
  | Returns:
  | :-
  | Returns Cohen's d (and its variance) as a measure of effect size (0.2 small; 0.5 medium; 0.8 large)
  """
  if paired:
    assert len(x) == len(y), "For paired samples, the size of x and y should be the same"
    diff = np.array(x) - np.array(y)
    n = len(diff)
    d = np.mean(diff) / np.std(diff, ddof = 1)
    var_d = 1 / n + d**2 / (2 * n)
  else:
    nx = len(x)
    ny = len(y)
    dof = nx + ny - 2
    d = (np.mean(x) - np.mean(y)) / np.sqrt(((nx-1)*np.std(x, ddof = 1) ** 2 + (ny-1)*np.std(y, ddof = 1) ** 2) / dof)
    var_d = (nx + ny) / (nx * ny) + d**2 / (2 * (nx + ny))
  return d, var_d


def mahalanobis_distance(x, y, paired = False):
  """calculates effect size between two groups in a multivariate comparison\n
  | Arguments:
  | :-
  | x (list or 1D-array or dataframe): comparison group containing numerical data
  | y (list or 1D-array or dataframe): comparison group containing numerical data
  | paired (bool): whether samples are paired or not (e.g., tumor & tumor-adjacent tissue from same patient); default:False\n
  | Returns:
  | :-
  | Returns Mahalanobis distance as a measure of effect size
  """
  if paired:
    assert x.shape == y.shape, "For paired samples, the size of x and y should be the same"
    x = np.array(x) - np.array(y)
    y = np.zeros_like(x)
  if isinstance(x, pd.DataFrame):
    x = x.values
  if isinstance(y, pd.DataFrame):
    y = y.values
  pooled_cov_inv = np.linalg.pinv((np.cov(x) + np.cov(y)) / 2)
  diff_means = (np.mean(y, axis = 1) - np.mean(x, axis = 1)).reshape(-1, 1)
  mahalanobis_d = np.sqrt(np.clip(diff_means.T @ pooled_cov_inv @ diff_means, 0, None))
  return mahalanobis_d[0][0]


def mahalanobis_variance(x, y, paired = False):
  """Estimates variance of Mahalanobis distance via bootstrapping\n
  | Arguments:
  | :-
  | x (list or 1D-array or dataframe): comparison group containing numerical data
  | y (list or 1D-array or dataframe): comparison group containing numerical data
  | paired (bool): whether samples are paired or not (e.g., tumor & tumor-adjacent tissue from same patient); default:False\n
  | Returns:
  | :-
  | Returns Mahalanobis distance as a measure of effect size
  """
  # Combine gp1 and gp2 into a single matrix
  data = np.concatenate((x.T, y.T), axis = 0)
  # Perform bootstrap resampling
  n_iterations = 1000
  # Initialize an empty array to store the bootstrap samples
  bootstrap_samples = np.empty(n_iterations)
  size_x = x.shape[1]
  for i in range(n_iterations):
      # Generate a random bootstrap sample
      sample = data[rng.choice(range(data.shape[0]), size = data.shape[0], replace = True)]
      # Split the bootstrap sample into two groups
      x_sample = sample[:size_x]
      y_sample = sample[size_x:]
      # Calculate the Mahalanobis distance for the bootstrap sample
      bootstrap_samples[i] = mahalanobis_distance(x_sample.T, y_sample.T, paired = paired)
  # Estimate the variance of the Mahalanobis distance
  return np.var(bootstrap_samples)


def variance_stabilization(data, groups = None):
  """Variance stabilization normalization\n
  | Arguments:
  | :-
  | data (dataframe): pandas dataframe with glycans/motifs as indices and samples as columns
  | groups (nested list): list containing lists of column names of samples from same group for group-specific normalization; otherwise global; default:None\n
  | Returns:
  | :-
  | Returns a dataframe in the same style as the input
  """
  # Apply log1p transformation
  data = np.log1p(data)
  # Scale data to have zero mean and unit variance
  if groups is None:
    data = (data - data.mean(axis = 0)) / data.std(axis = 0, ddof = 1)
  else:
    for group in groups:
      group_data = data[group]
      data[group] = (group_data - group_data.mean(axis = 0)) / group_data.std(axis = 0, ddof = 1)
  return data


class MissForest:
  """Parameters
  (adapted from https://github.com/yuenshingyan/MissForest)
  ----------
  regressor : estimator object.
  A object of that type is instantiated for each imputation.
  This object is assumed to implement the scikit-learn estimator API.

  n_iter : int
  Determines the number of iterations for the imputation process.
  """

  def __init__(self, regressor = RandomForestRegressor(n_jobs = -1), max_iter = 5, tol = 1e-6):
    self.regressor = regressor
    self.max_iter = max_iter
    self.tol = tol

  def fit_transform(self, X: pd.DataFrame) -> pd.DataFrame:
    # Step 1: Initialization 
    # Keep track of where NaNs are in the original dataset
    X_nan = X.isnull()
    # Replace NaNs with median of the column in a new dataset that will be transformed
    X_transform = X.fillna(X.median())
    # Sort columns by the number of NaNs (ascending)
    sorted_columns = X_nan.sum().sort_values().index
    for _ in range(self.max_iter):
      total_change = 0
      # Step 2: Imputation
      for column in sorted_columns:
        missing_idx = X_nan[column]
        if missing_idx.any():  # if column has missing values in original dataset
          # Split data into observed and missing for the current column
          observed = X_transform.loc[~missing_idx]
          missing = X_transform.loc[missing_idx]
          # Use other columns to predict the current column
          self.regressor.fit(observed.drop(columns = column), observed[column])
          y_missing_pred = self.regressor.predict(missing.drop(columns = column))
          # Replace missing values in the current column with predictions
          total_change += np.sum(np.abs(X_transform.loc[missing_idx, column] - y_missing_pred))
          X_transform.loc[missing_idx, column] = y_missing_pred
      # Check for convergence
      if total_change < self.tol:
        break  # Break out of the loop if converged
    # Avoiding zeros
    X_transform += 1e-6
    return X_transform


def impute_and_normalize(df, groups, impute = True, min_samples = None):
    """given a dataframe, discards rows with too many missings, imputes the rest, and normalizes\n
    | Arguments:
    | :-
    | df (dataframe): dataframe containing glycan sequences in first column and relative abundances in subsequent columns
    | groups (list): nested list of column name lists, one list per group
    | impute (bool): replaces zeroes with predictions from MissForest; default:True
    | min_samples (int): How many samples per group need to have non-zero values for glycan to be kept; default: at least half per group\n
    | Returns:
    | :-
    | Returns a dataframe in the same style as the input 
    """
    if min_samples is None:
      min_samples = [len(group_cols) // 2 for group_cols in groups]
    else:
      min_samples = [min_samples] * len(groups)
    masks = [(df[group_cols] != 0).sum(axis = 1) >= thresh for group_cols, thresh in zip(groups, min_samples)]
    df = df[np.all(masks, axis = 0)]
    colname = df.columns[0]
    glycans = df[colname]
    df = df.iloc[:, 1:]
    old_cols = []
    if isinstance(colname, int):
      old_cols = df.columns
      df.columns = df.columns.astype(str)
    if impute:
      mf = MissForest()
      df.replace(0, np.nan, inplace = True)
      df = mf.fit_transform(df)
    df = (df / df.sum(axis = 0)) * 100
    if len(old_cols) > 0:
      df.columns = old_cols
    df.insert(loc = 0, column = colname, value = glycans)
    return df


def variance_based_filtering(df, min_feature_variance = 0.01):
    """Variance-based filtering of features\n
    | Arguments:
    | :-
    | df (dataframe): dataframe containing glycan sequences in index and samples in columns
    | min_feature_variance (float): Minimum variance to include a feature in the analysis\n
    | Returns:
    | :-
    | Returns a pandas DataFrame with remaining glycans as indices and samples in columns
    """
    return df[df.var(axis = 1) > min_feature_variance]


def jtkdist(timepoints, param_dic, reps = 1, normal = False):
  """Precalculates all possible JT test statistic permutation probabilities for reference later, speeding up the
  | analysis. Calculates the exact null distribution using the Harding algorithm.\n
  | Arguments:
  | :-
  | timepoints (int): number of timepoints within the experiment.
  | param_dic (dict): dictionary carrying around the parameter values
  | reps (int): number of replicates within each timepoint.
  | normal (bool): a flag for normal approximation if maximum possible negative log p-value is too large.\n
  | Returns:
  | :-
  | Returns statistical values, added to 'param_dic'.
  """
  timepoints = timepoints if isinstance(timepoints, int) else timepoints.sum()
  tim = np.full(timepoints, reps) if reps != timepoints else reps  # Support for unbalanced replication (unequal replicates in all groups)
  maxnlp = gammaln(np.sum(tim)) - np.sum(np.log(np.arange(1, np.max(tim)+1)))
  limit = math.log(float('inf'))
  normal = normal or (maxnlp > limit - 1)  # Switch to normal approximation if maxnlp is too large
  lab = []
  nn = sum(tim)  # Number of data values (Independent of period and lag)
  M = (nn ** 2 - np.sum(np.square(tim))) / 2  # Max possible jtk statistic
  param_dic.update({"GRP_SIZE": tim, "NUM_GRPS": len(tim), "NUM_VALS": nn,
                    "MAX": M, "DIMS": [int(nn * (nn - 1) / 2), 1]})
  if normal:
    param_dic["VAR"] = (nn ** 2 * (2 * nn + 3) - np.sum(np.square(tim) * (2 * t + 3) for t in tim)) / 72  # Variance of JTK
    param_dic["SDV"] = math.sqrt(param_dic["VAR"])  # Standard deviation of JTK
    param_dic["EXV"] = M / 2  # Expected value of JTK
    param_dic["EXACT"] = False
  MM = int(M // 2)  # Mode of this possible alternative to JTK distribution
  cf = [1] * (MM + 1)  # Initial lower half cumulative frequency (cf) distribution
  size = sorted(tim)  # Sizes of each group of known replicate values, in ascending order for fastest calculation
  k = len(tim)  # Number of groups of replicates
  N = [size[k-1]]
  if k > 2:
    for i in range(k - 1, 1, -1):  # Count permutations using the Harding algorithm
      N.insert(0, (size[i] + N[0]))
  for m, n in zip(size[:-1], N):
    update_cf_for_m_n(m, n, MM, cf)
  cf = np.array(cf)
  # cf now contains the lower half cumulative frequency distribution
  # append the symmetric upper half cumulative frequency distribution to cf
  if M % 2:   # jtkcf = upper-tail cumulative frequencies for all integer jtk
    jtkcf = np.concatenate((cf, 2 * cf[MM] - cf[:MM][::-1], [2 * cf[MM]]))[::-1]
  else:
    jtkcf = np.concatenate((cf, cf[MM - 1] + cf[MM] - cf[:MM-1][::-1], [cf[MM - 1] + cf[MM]]))[::-1]
  ajtkcf = list((jtkcf[i - 1] + jtkcf[i]) / 2 for i in range(1, len(jtkcf)))  # interpolated cumulative frequency values for all half-intgeger jtk
  cf = [ajtkcf[(j - 1) // 2] if j % 2 == 0 else jtkcf[j // 2] for j in [i for i in range(1, 2 * int(M) + 2)]]
  param_dic["CP"] = [c / jtkcf[0] for c in cf]  # all upper-tail p-values
  return param_dic


def jtkinit(periods, param_dic, interval = 1, replicates = 1):
  """Defines the parameters of the simulated sine waves for reference later.\n
  | Each molecular species within the analysis is matched to the optimal wave defined here, and the parameters
  | describing that wave are attributed to the molecular species.\n
  | Arguments:
  | :-
  | periods (list): the possible periods of rhytmicity in the biological data (valued as 'number of timepoints').
  | (note: periods can accept multiple values (ie, you can define circadian rhythms as between 22, 24, 26 hours))
  | param_dic (dict): dictionary carrying around the parameter values
  | interval (int): the number of units of time (arbitrary) between each experimental timepoint.
  | replicates (int): number of replicates within each group.\n
  | Returns:
  | :-
  | Returns values describing waveforms, added to 'param_dic'.
  """
  param_dic["INTERVAL"] = interval
  if len(periods) > 1:
    param_dic["PERIODS"] = list(periods)
  else:
    param_dic["PERIODS"] = list(periods)
  param_dic["PERFACTOR"] = np.concatenate([np.repeat(i, ti) for i, ti in enumerate(periods, start = 1)])
  tim = np.array(param_dic["GRP_SIZE"])
  timepoints = int(param_dic["NUM_GRPS"])
  timerange = np.arange(timepoints)  # Zero-based time indices
  param_dic["SIGNCOS"] = np.zeros((periods[0], ((math.floor(timepoints / (periods[0]))*int(periods[0]))* replicates)), dtype = int)
  for i, period in enumerate(periods):
    time2angle = np.array([(2*round(math.pi, 4))/period])  # convert time to angle using an ~pi value
    theta = timerange*time2angle  # zero-based angular values across time indices
    cos_v = np.cos(theta)  # unique cosine values at each time point
    cos_r = np.repeat(rankdata(cos_v), np.max(tim))  # replicated ranks of unique cosine values
    cgoos = np.sign(np.subtract.outer(cos_r, cos_r)).astype(int)
    lower_tri = []
    for col in range(len(cgoos)):
      for row in range(col + 1, len(cgoos)):
        lower_tri.append(cgoos[row, col])
    cgoos = np.array(lower_tri)
    cgoosv = np.array(cgoos).reshape(param_dic["DIMS"])
    param_dic["CGOOSV"] = []
    param_dic["CGOOSV"].append(np.zeros((cgoos.shape[0], period)))
    param_dic["CGOOSV"][i][:, 0] = cgoosv[:, 0]
    cycles = math.floor(timepoints / period)
    jrange = np.arange(cycles * period)
    cos_s = np.sign(cos_v)[jrange]
    cos_s = np.repeat(cos_s, (tim[jrange]))
    if replicates == 1:
      param_dic["SIGNCOS"][:, i] = cos_s
    else:
      param_dic["SIGNCOS"][i] = cos_s
    for j in range(1, period):  # One-based half-integer lag index j
      delta_theta = j * time2angle / 2  # Angles of half-integer lags
      cos_v = np.cos(theta + delta_theta)  # Cycle left
      cos_r = np.concatenate([np.repeat(val, num) for val, num in zip(rankdata(cos_v), tim)]) # Phase-shifted replicated ranks
      cgoos = np.sign(np.subtract.outer(cos_r, cos_r)).T
      mask = np.triu(np.ones(cgoos.shape), k = 1).astype(bool)
      mask[np.diag_indices(mask.shape[0])] = False
      cgoos = cgoos[mask]
      cgoosv = cgoos.reshape(param_dic["DIMS"])
      matrix_i = param_dic["CGOOSV"][i]
      matrix_i[:, j] = cgoosv.flatten()
      param_dic["CGOOSV[i]"] = matrix_i
      cos_v = cos_v.flatten()
      cos_s = np.sign(cos_v)[jrange]
      cos_s = np.repeat(cos_s, (tim[jrange]))
      if replicates == 1:
        param_dic["SIGNCOS"][:, j] = cos_s
      else:
        param_dic["SIGNCOS"][j] = cos_s
  return param_dic


def jtkstat(z, param_dic):
  """Determines the JTK statistic and p-values for all model phases, compared to expression data.\n
  | Arguments:
  | :-
  | z (pd.DataFrame): expression data for a molecule ordered in groups, by timepoint.
  | param_dic (dict): a dictionary containing parameters defining model waveforms.\n
  | Returns:
  | :-
  | Returns an updated parameter dictionary where the appropriate model waveform has been assigned to the
  | molecules in the analysis.
  """
  param_dic["CJTK"] = []
  M = param_dic["MAX"]
  z = np.array(z)
  foosv = np.sign(np.subtract.outer(z, z)).T  # Due to differences in the triangle indexing of R / Python we need to transpose and select upper triangle rather than the lower triangle
  mask = np.triu(np.ones(foosv.shape), k = 1).astype(bool) # Additionally, we need to remove the middle diagonal from the tri index
  mask[np.diag_indices(mask.shape[0])] = False
  foosv = foosv[mask].reshape(param_dic["DIMS"])
  for i in range(param_dic["PERIODS"][0]):
    cgoosv = param_dic["CGOOSV"][0][:, i]
    S = np.nansum(np.diag(foosv * cgoosv))
    jtk = (abs(S) + M) / 2  # Two-tailed JTK statistic for this lag and distribution
    if S == 0:
      param_dic["CJTK"].append([1, 0, 0])
    elif param_dic.get("EXACT", False):
      jtki = 1 + 2 * int(jtk)  # index into the exact upper-tail distribution
      p = 2 * param_dic["CP"][jtki-1]
      param_dic["CJTK"].append([p, S, S / M])
    else:
      p = 2 * norm.cdf(-(jtk - 0.5), -param_dic["EXV"], param_dic["SDV"])
      param_dic["CJTK"].append([p, S, S / M])  # include tau = s/M for this lag and distribution
  return param_dic


def jtkx(z, param_dic, ampci = False):
  """Deployment of jtkstat for repeated use, and parameter extraction\n
  | Arguments:
  | :-
  | z (pd.dataframe): expression data ordered in groups, by timepoint.
  | param_dic (dict): a dictionary containing parameters defining model waveforms.
  | ampci (bool): flag for calculating amplitude confidence interval (TRUE = compute); default=False.\n
  | Returns:
  | :-
  | Returns an updated parameter dictionary containing the optimal waveform parameters for each molecular species.
  """
  param_dic = jtkstat(z, param_dic)  # Calculate p and S for all phases
  pvals = [cjtk[0] for cjtk in param_dic["CJTK"]]  # Exact two-tailed p values for period/phase combos
  padj = multipletests(pvals, method = 'fdr_bh')[1]
  JTK_ADJP = min(padj)  # Global minimum adjusted p-value
  def groupings(padj, param_dic):
    d = defaultdict(list)
    for i, value in enumerate(padj):
      key = param_dic["PERFACTOR"][i]
      d[key].append(value)
    return dict(d)
  dpadj = groupings(padj, param_dic)
  padj = np.array(pd.DataFrame(dpadj.values()).T)
  minpadj = [padj[i].min() for i in range(0, np.shape(padj)[1])]  # Minimum adjusted p-values for each period
  if len(param_dic["PERIODS"]) > 1:
    pers_index = np.where(JTK_ADJP == minpadj)[0]  # indices of all optimal periods
  else:
    pers_index = 0
  pers = param_dic["PERIODS"][int(pers_index)]    # all optimal periods
  padj_values = padj[pers_index]
  lagis = np.where(padj == JTK_ADJP)[0]  # list of optimal lag indice for each optimal period
  best_results = {'bestper': 0, 'bestlag': 0, 'besttau': 0, 'maxamp': 0, 'maxamp_ci': 2, 'maxamp_pval': 0}
  sc = np.transpose(param_dic["SIGNCOS"])
  w = (z[:len(sc)] - hlm(z[:len(sc)])) * math.sqrt(2)
  for i in range(abs(pers)):
    for lagi in lagis:
      S = param_dic["CJTK"][lagi][1]
      s = np.sign(S) if S != 0 else 1
      lag = (pers + (1 - s) * pers / 4 - lagi / 2) % pers
      signcos = sc[:, lagi]
      tmp = s * w * sc[:, lagi]
      amp = hlm(tmp)  # Allows missing values
      if ampci:
        jtkwt = pd.DataFrame(wilcoxon(tmp[np.isfinite(tmp)], zero_method = 'wilcox', correction = False,
                                              alternatives = 'two-sided', mode = 'exact'))
        amp = jtkwt['confidence_interval'].median()  # Extract estimate (median) from the conf. interval
        best_results['maxamp_ci'] = jtkwt['confidence_interval'].values
        best_results['maxamp_pval'] = jtkwt['pvalue'].values
      if amp > best_results['maxamp']:
        best_results.update({'bestper': pers, 'bestlag': lag, 'besttau': [abs(param_dic["CJTK"][lagi][2])], 'maxamp': amp})
  JTK_PERIOD = param_dic["INTERVAL"] * best_results['bestper']
  JTK_LAG = param_dic["INTERVAL"] * best_results['bestlag']
  JTK_AMP = float(max(0, best_results['maxamp']))
  JTK_TAU = best_results['besttau']
  JTK_AMP_CI = best_results['maxamp_ci']
  JTK_AMP_PVAL = best_results['maxamp_pval']
  return pd.Series([JTK_ADJP, JTK_PERIOD, JTK_LAG, JTK_AMP])


def get_BF(n, p, z = False, method = "robust", upper = 10):
  """Transforms a p-value into Jeffreys' approximate Bayes factor (BF)\n
  | Arguments:
  | :-
  | n (int): Sample size.
  | p (float): The p-value.
  | z (bool): True if the p-value is based on a z-statistic, False if t-statistic; default:False
  | method (str): Method used for the choice of 'b'. Options are "JAB", "min", "robust", "balanced"; default:'robust'
  | upper (float): The upper limit for the range of realistic effect sizes. Only relevant when method="balanced"; default:10\n
  | Returns:
  | :-
  | float: A numeric value for the BF in favour of H1.
  """
  method_dict = {
    "JAB": lambda n: 1/n,
    "min": lambda n: 2/n,
    "robust": lambda n: max(2/n, 1/np.sqrt(n)),
    }
  if method == "balanced":
    integrand = lambda x: np.exp(-n * x**2 / 4)
    method_dict["balanced"] = lambda n: max(2/n, min(0.5, integrate.quad(integrand, 0, upper)[0]))
  t_statistic = norm.ppf(1 - p/2) if z else t.ppf(1 - p/2, n - 2)
  b = method_dict.get(method, lambda n: 1/n)(n)
  BF = np.exp(0.5 * t_statistic**2) * np.sqrt(b)
  return BF


def get_alphaN(n, BF = 3, method = "robust", upper = 10):
  """Set the alpha level based on sample size via Bayesian-Adaptive Alpha Adjustment.\n
  | Arguments:
  | :-
  | n (int): Sample size.
  | BF (float): Bayes factor you would like to match; default:3
  | method (str): Method used for the choice of 'b'. Options are "JAB", "min", "robust", "balanced"; default:"robust"
  | upper (float): The upper limit for the range of realistic effect sizes. Only relevant when method="balanced"; default:10\n
  | Returns:
  | :-
  | float: Numeric alpha level required to achieve the desired level of evidence.
  """
  method_dict = {
    "JAB": lambda n: 1/n,
    "min": lambda n: 2/n,
    "robust": lambda n: max(2/n, 1/np.sqrt(n)),
    }
  if method == "balanced":
    integrand = lambda x: np.exp(-n * x**2 / 4)
    method_dict["balanced"] = lambda n: max(2/n, min(0.5, integrate.quad(integrand, 0, upper)[0]))
  b = method_dict.get(method, lambda n: 1/n)(n)
  alpha = 1 - chi2.cdf(2 * np.log(BF / np.sqrt(b)), 1)
  return alpha


def pi0_tst(p_values, alpha = 0.05):
  """estimate the proportion of true null hypotheses in a set of p-values\n
  | Arguments:
  | :-
  | p_values (array): array of p-values
  | alpha (float): significance threshold for testing; default:0.05\n
  | Returns:
  | :-
  | Returns an estimate of π0, the proportion of true null hypotheses in that dataset
  """
  alpha_prime = alpha / (1 + alpha)
  n = len(p_values)
  # Apply the BH procedure at level α'
  sorted_indices = np.argsort(p_values)
  sorted_p_values = p_values[sorted_indices] 
  bh_values = (n / rankdata(sorted_p_values)) * sorted_p_values
  corrected_p_values = np.minimum.accumulate(bh_values[::-1])[::-1]
  corrected_p_values_sorted_indices = np.argsort(sorted_indices)
  corrected_p_values = corrected_p_values[corrected_p_values_sorted_indices]
  # Estimate π0
  rejected = corrected_p_values < alpha_prime
  n_rejected = np.sum(rejected)
  pi0_estimate = (n - n_rejected) / n
  return pi0_estimate


def TST_grouped_benjamini_hochberg(identifiers_grouped, p_values_grouped, alpha):
  """perform the two-stage adaptive Benjamini-Hochberg procedure for multiple testing correction\n
  | Arguments:
  | :-
  | identifiers_grouped (dict): dictionary of group : list of glycans
  | p_values_grouped (dict): dictionary of group : list of p-values
  | alpha (float): significance threshold for testing\n
  | Returns:
  | :-
  | Returns dictionaries of glycan : corrected p-value and glycan : significant?
  """
  # Initialize results
  adjusted_p_values = {}
  significance_dict = {}
  for group, group_p_values in p_values_grouped.items():
    group_p_values = np.array(group_p_values)
    # Estimate π0 for the group within the Two-Stage method
    pi0_estimate = pi0_tst(group_p_values, alpha)
    if pi0_estimate == 1:
      adjusted_p_values[identifier] = [1.0] * len(group_p_values)
      continue
    n = len(group_p_values)
    sorted_indices = np.argsort(group_p_values)
    sorted_p_values = group_p_values[sorted_indices]
    # Weight the alpha value by π0 estimate
    adjusted_alpha = alpha / pi0_estimate
    # Calculate the BH adjusted p-values
    ecdffactor = (np.arange(1, n + 1) / n)
    pvals_corrected_raw = sorted_p_values / (ecdffactor)
    group_adjusted_p_values = np.minimum.accumulate(pvals_corrected_raw[::-1])[::-1]
    group_adjusted_p_values_sorted_indices = np.argsort(sorted_indices)
    group_adjusted_p_values = group_adjusted_p_values[group_adjusted_p_values_sorted_indices]
    group_adjusted_p_values = np.minimum(group_adjusted_p_values, 1)
    group_adjusted_p_values = np.maximum(group_adjusted_p_values, group_p_values)
    for identifier, corrected_pval in zip(identifiers_grouped[group], group_adjusted_p_values):
      adjusted_p_values[identifier] = corrected_pval
      significance_dict[identifier] = corrected_pval < adjusted_alpha
  return adjusted_p_values, significance_dict


def test_inter_vs_intra_group(cohort_b, cohort_a, glycans, grouped_glycans):
  """estimates intra- and inter-group correlation of a given grouping of glycans via a mixed-effects model\n
  | Arguments:
  | :-
  | cohort_b (dataframe): dataframe of glycans as rows and samples as columns of the case samples
  | cohort_a (dataframe): dataframe of glycans as rows and samples as columns of the control samples
  | glycans (list): list of glycans in IUPAC-condensed nomenclature
  | grouped_glycans (dict): dictionary of type group : glycans\n
  | Returns:
  | :-
  | Returns floats for the intra-group and inter-group correlation
  """
  reverse_lookup = {k: v for v, l in grouped_glycans.items() for k in l}
  temp = pd.DataFrame(np.log2(abs((cohort_b.values + 1e-8) / (cohort_a.values + 1e-8))))
  temp.index = glycans
  temp = temp.reset_index()
  # Melt the dataframe to long format
  temp = temp.melt(id_vars = 'index', var_name = 'glycan', value_name = 'measurement')
  # Rename the columns appropriately
  temp.columns= ["glycan", "sample_id", "diffs"]
  temp["group_id"] = [reverse_lookup[g] for g in temp.glycan]
  # Define the model
  md = smf.mixedlm("diffs ~ C(group_id)", temp,
                     groups = temp["sample_id"],
                     re_formula = "~1",  # Random intercept for glycans
                     vc_formula = {"glycan": "0 + C(glycan)"}) # Variance component for glycans
  # Fit the model
  with warnings.catch_warnings():
    warnings.simplefilter("ignore", category = ConvergenceWarning)
    mdf = md.fit()
  # Extract variance components
  var_samples = mdf.cov_re.iloc[0, 0]  # Variance due to differences among groups of glycans (inter-group)
  var_glycans_within_group = mdf.vcomp[0] # Variance due to differences among glycans within the same group (intra-group)
  residual_var = mdf.scale  # Residual variance
  # Total variance
  total_var = var_samples + var_glycans_within_group + residual_var
  # Calculate Intra-group Correlation (ICC)
  icc = var_glycans_within_group / total_var
  # Calculate Inter-group Correlation
  inter_group_corr = var_samples / total_var
  return icc, inter_group_corr