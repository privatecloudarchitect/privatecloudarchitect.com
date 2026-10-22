# A job whose sign-in parameters come from a hashtable, which the script cannot read.
$sign = @{ Server = 'vcenter.example.net' }
Connect-VIServer @sign
